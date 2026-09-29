from app.auth import verifier as verifier_port
from app.infra.mcp import auth as mcp_auth


class _FakeContainer:
    """Stands in for dishka.AsyncContainer: only .get() is exercised here."""

    def __init__(self, verifier: verifier_port.TokenVerifier) -> None:
        self._verifier = verifier

    async def get(self, _type: object) -> verifier_port.TokenVerifier:
        return self._verifier


class _FakeVerifier:
    def __init__(self, result: verifier_port.VerifiedToken | None) -> None:
        self._result = result

    async def verify(self, token: str) -> verifier_port.VerifiedToken | None:  # noqa: ARG002
        return self._result


class TestVerifyToken:
    async def test_returns_access_token_with_claims(self) -> None:
        fake_verifier = _FakeVerifier(
            verifier_port.VerifiedToken(
                claims={"sub": "usr_abc", "email": "a@example.com"}
            )
        )
        provider = mcp_auth.build_auth_provider(_FakeContainer(fake_verifier))  # type: ignore[arg-type]

        result = await provider.verify_token("mmcp_something")

        assert result is not None
        assert result.client_id == "usr_abc"
        assert result.claims == {"sub": "usr_abc", "email": "a@example.com"}
        assert result.scopes == []

    async def test_returns_none_when_the_port_rejects_it(self) -> None:
        provider = mcp_auth.build_auth_provider(_FakeContainer(_FakeVerifier(None)))  # type: ignore[arg-type]

        assert await provider.verify_token("mmcp_garbage") is None
