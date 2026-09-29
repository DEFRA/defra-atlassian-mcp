import fastapi
import pytest

from app.auth import verifier as verifier_port
from app.identity import service as identity_service
from app.infra.rest.auth import resolver
from tests.fakes import in_memory_identity_store


def _make_request(headers: dict[str, str] | None = None) -> fastapi.Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": raw_headers,
    }
    return fastapi.Request(scope)


class _FakeVerifier:
    def __init__(self, result: verifier_port.VerifiedToken | None) -> None:
        self._result = result

    async def verify(self, token: str) -> verifier_port.VerifiedToken | None:  # noqa: ARG002
        return self._result


@pytest.fixture
def identity() -> identity_service.IdentityService:
    return identity_service.IdentityService(
        in_memory_identity_store.InMemoryUserStore()
    )


class TestTrustedHeaderUserResolver:
    async def test_creates_a_user_on_first_sight(
        self, identity: identity_service.IdentityService
    ) -> None:
        resolver_under_test = resolver.TrustedHeaderUserResolver("X-User-Id", identity)

        principal = await resolver_under_test.resolve(
            _make_request({"X-User-Id": "dev@example.com"})
        )

        assert principal.email == "dev@example.com"
        assert principal.user_id == "dev@example.com"
        assert principal.scopes == frozenset()

    async def test_is_stable_across_calls(
        self, identity: identity_service.IdentityService
    ) -> None:
        resolver_under_test = resolver.TrustedHeaderUserResolver("X-User-Id", identity)

        first = await resolver_under_test.resolve(
            _make_request({"X-User-Id": "dev@example.com"})
        )
        second = await resolver_under_test.resolve(
            _make_request({"X-User-Id": "dev@example.com"})
        )

        assert first.user_id == second.user_id

    async def test_requires_the_header(
        self, identity: identity_service.IdentityService
    ) -> None:
        resolver_under_test = resolver.TrustedHeaderUserResolver("X-User-Id", identity)

        with pytest.raises(fastapi.HTTPException) as exc_info:
            await resolver_under_test.resolve(_make_request())
        assert exc_info.value.status_code == 400


class TestPersonalTokenUserResolver:
    async def test_builds_principal_from_claims(self) -> None:
        fake = _FakeVerifier(
            verifier_port.VerifiedToken(
                claims={
                    "sub": "usr_abc",
                    "email": "a@example.com",
                    "label": "Claude Code",
                    "token_id": "pat_1",
                }
            )
        )
        resolver_under_test = resolver.PersonalTokenUserResolver(fake)

        principal = await resolver_under_test.resolve(
            _make_request({"Authorization": "Bearer mmcp_something"})
        )

        assert principal.user_id == "usr_abc"
        assert principal.email == "a@example.com"
        assert principal.label == "Claude Code"
        assert principal.token_id == "pat_1"

    async def test_requires_bearer_header(self) -> None:
        resolver_under_test = resolver.PersonalTokenUserResolver(_FakeVerifier(None))

        with pytest.raises(fastapi.HTTPException) as exc_info:
            await resolver_under_test.resolve(_make_request())
        assert exc_info.value.status_code == 401

    async def test_rejects_an_unverifiable_token(self) -> None:
        resolver_under_test = resolver.PersonalTokenUserResolver(_FakeVerifier(None))

        with pytest.raises(fastapi.HTTPException) as exc_info:
            await resolver_under_test.resolve(
                _make_request({"Authorization": "Bearer mmcp_bad"})
            )
        assert exc_info.value.status_code == 401
