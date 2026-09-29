import pytest

from app.identity import service as identity_service
from app.infra.auth import personal_token
from tests.fakes import in_memory_identity_store

_PREFIX = "amcp_"  # noqa: S105 -- matches identity_service._TOKEN_PREFIX


@pytest.fixture
def users() -> in_memory_identity_store.InMemoryUserStore:
    return in_memory_identity_store.InMemoryUserStore()


@pytest.fixture
def pat_store() -> in_memory_identity_store.InMemoryPersonalAccessTokenStore:
    return in_memory_identity_store.InMemoryPersonalAccessTokenStore()


@pytest.fixture
def identity(
    users: in_memory_identity_store.InMemoryUserStore,
) -> identity_service.IdentityService:
    return identity_service.IdentityService(users)


@pytest.fixture
def tokens(
    pat_store: in_memory_identity_store.InMemoryPersonalAccessTokenStore,
) -> identity_service.PersonalTokenService:
    return identity_service.PersonalTokenService(
        pat_store,
        default_ttl_days=90,
        max_ttl_days=365,
        last_used_throttle_seconds=300,
    )


@pytest.fixture
def verifier(
    tokens: identity_service.PersonalTokenService,
    identity: identity_service.IdentityService,
) -> personal_token.PersonalTokenVerifier:
    return personal_token.PersonalTokenVerifier(tokens, identity)


class TestVerify:
    async def test_returns_claims_for_a_valid_token(
        self,
        verifier: personal_token.PersonalTokenVerifier,
        tokens: identity_service.PersonalTokenService,
        identity: identity_service.IdentityService,
    ) -> None:
        user = await identity.get_or_create("a@example.com")
        _, secret = await tokens.mint(user.user_id, "Claude Code")

        result = await verifier.verify(secret)

        assert result is not None
        assert result.claims["sub"] == user.user_id
        assert result.claims["email"] == "a@example.com"
        assert result.claims["label"] == "Claude Code"

    async def test_returns_none_for_unknown_token(
        self, verifier: personal_token.PersonalTokenVerifier
    ) -> None:
        assert await verifier.verify(f"{_PREFIX}garbage") is None

    async def test_returns_none_for_revoked_token(
        self,
        verifier: personal_token.PersonalTokenVerifier,
        tokens: identity_service.PersonalTokenService,
        identity: identity_service.IdentityService,
    ) -> None:
        user = await identity.get_or_create("a@example.com")
        record, secret = await tokens.mint(user.user_id, "Claude Code")
        await tokens.revoke(user.user_id, record.id)

        assert await verifier.verify(secret) is None

    async def test_returns_none_when_the_user_has_been_deleted(
        self,
        verifier: personal_token.PersonalTokenVerifier,
        tokens: identity_service.PersonalTokenService,
        identity: identity_service.IdentityService,
        users: in_memory_identity_store.InMemoryUserStore,
    ) -> None:
        """A valid, unexpired token whose owning user no longer exists must
        not verify — the user could have been deleted after the token was
        minted.
        """
        user = await identity.get_or_create("a@example.com")
        _, secret = await tokens.mint(user.user_id, "Claude Code")
        users._by_user_id.pop(user.user_id)  # noqa: SLF001 -- simulate deletion

        assert await verifier.verify(secret) is None
