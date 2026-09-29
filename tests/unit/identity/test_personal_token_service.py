import datetime

import pytest

from app.identity import exceptions
from app.identity import service as identity_service
from tests.fakes import in_memory_identity_store

_PREFIX = "amcp_"  # noqa: S105 -- matches identity_service._TOKEN_PREFIX


@pytest.fixture
def tokens() -> in_memory_identity_store.InMemoryPersonalAccessTokenStore:
    return in_memory_identity_store.InMemoryPersonalAccessTokenStore()


@pytest.fixture
def service(
    tokens: in_memory_identity_store.InMemoryPersonalAccessTokenStore,
) -> identity_service.PersonalTokenService:
    return identity_service.PersonalTokenService(
        tokens,
        default_ttl_days=90,
        max_ttl_days=365,
        last_used_throttle_seconds=300,
    )


class TestMint:
    async def test_returns_a_record_and_the_plaintext_secret(
        self, service: identity_service.PersonalTokenService
    ) -> None:
        record, secret = await service.mint("usr_abc", "Claude Code")

        assert secret.startswith(_PREFIX)
        assert record.user_id == "usr_abc"
        assert record.label == "Claude Code"
        assert record.is_active is True

    async def test_never_persists_the_plaintext_secret(
        self,
        service: identity_service.PersonalTokenService,
        tokens: in_memory_identity_store.InMemoryPersonalAccessTokenStore,
    ) -> None:
        record, secret = await service.mint("usr_abc", "Claude Code")

        stored = await tokens.get(record.id)
        assert stored is not None
        assert stored.token_hash != secret
        assert secret not in stored.model_dump_json()

    async def test_ttl_is_clamped_to_max(
        self, tokens: in_memory_identity_store.InMemoryPersonalAccessTokenStore
    ) -> None:
        service = identity_service.PersonalTokenService(
            tokens,
            default_ttl_days=90,
            max_ttl_days=30,
            last_used_throttle_seconds=300,
        )
        record, _ = await service.mint("usr_abc", "CI", ttl_days=9999)

        span = record.expires_at - record.created_at
        assert span <= datetime.timedelta(days=30, hours=1)


class TestVerify:
    async def test_returns_the_record_for_a_valid_secret(
        self, service: identity_service.PersonalTokenService
    ) -> None:
        _, secret = await service.mint("usr_abc", "Claude Code")

        record = await service.verify(secret)

        assert record.user_id == "usr_abc"

    async def test_rejects_an_unknown_secret(
        self, service: identity_service.PersonalTokenService
    ) -> None:
        with pytest.raises(exceptions.UnknownTokenError):
            await service.verify(f"{_PREFIX}not-a-real-token")

    async def test_rejects_a_secret_with_the_wrong_prefix(
        self, service: identity_service.PersonalTokenService
    ) -> None:
        """A malformed/foreign-prefix secret is rejected without a store lookup."""
        with pytest.raises(exceptions.UnknownTokenError):
            await service.verify("not-our-prefix-at-all")

    async def test_rejects_a_revoked_token(
        self, service: identity_service.PersonalTokenService
    ) -> None:
        record, secret = await service.mint("usr_abc", "Claude Code")
        await service.revoke("usr_abc", record.id)

        with pytest.raises(exceptions.TokenRevokedError):
            await service.verify(secret)

    async def test_rejects_an_expired_token(
        self,
        service: identity_service.PersonalTokenService,
        tokens: in_memory_identity_store.InMemoryPersonalAccessTokenStore,
    ) -> None:
        """Mint normally and age the stored record, rather than
        reconstructing PersonalTokenService's own hash -- coupling this
        test to that implementation would let it drift from whatever
        mint() actually does."""
        record, secret = await service.mint("usr_abc", "Claude Code")
        expired = record.model_copy(
            update={
                "expires_at": datetime.datetime.now(datetime.UTC)
                - datetime.timedelta(days=1)
            }
        )
        await tokens.create(expired)

        with pytest.raises(exceptions.TokenExpiredError):
            await service.verify(secret)

    async def test_touches_last_used_when_stale(
        self,
        service: identity_service.PersonalTokenService,
        tokens: in_memory_identity_store.InMemoryPersonalAccessTokenStore,
    ) -> None:
        record, secret = await service.mint("usr_abc", "Claude Code")
        assert record.last_used_at is None

        await service.verify(secret)

        updated = await tokens.get(record.id)
        assert updated is not None
        assert updated.last_used_at is not None

    async def test_does_not_touch_last_used_within_the_throttle_window(
        self, tokens: in_memory_identity_store.InMemoryPersonalAccessTokenStore
    ) -> None:
        service = identity_service.PersonalTokenService(
            tokens,
            default_ttl_days=90,
            max_ttl_days=365,
            last_used_throttle_seconds=3600,
        )
        record, secret = await service.mint("usr_abc", "Claude Code")
        first_seen = datetime.datetime.now(datetime.UTC)
        await tokens.touch_last_used(record.id, first_seen)

        await service.verify(secret)

        updated = await tokens.get(record.id)
        assert updated is not None
        assert updated.last_used_at == first_seen


class TestListForUser:
    async def test_only_returns_that_users_tokens(
        self, service: identity_service.PersonalTokenService
    ) -> None:
        await service.mint("usr_abc", "one")
        await service.mint("usr_abc", "two")
        await service.mint("usr_other", "three")

        result = await service.list_for_user("usr_abc")

        assert {t.label for t in result} == {"one", "two"}


class TestRevoke:
    async def test_marks_the_token_inactive(
        self, service: identity_service.PersonalTokenService
    ) -> None:
        record, secret = await service.mint("usr_abc", "Claude Code")

        await service.revoke("usr_abc", record.id)

        with pytest.raises(exceptions.TokenRevokedError):
            await service.verify(secret)

    async def test_rejects_a_token_belonging_to_another_user(
        self, service: identity_service.PersonalTokenService
    ) -> None:
        record, _ = await service.mint("usr_abc", "Claude Code")

        with pytest.raises(exceptions.TokenNotFoundError):
            await service.revoke("usr_someone_else", record.id)

    async def test_rejects_an_unknown_token_id(
        self, service: identity_service.PersonalTokenService
    ) -> None:
        with pytest.raises(exceptions.TokenNotFoundError):
            await service.revoke("usr_abc", "pat_does-not-exist")
