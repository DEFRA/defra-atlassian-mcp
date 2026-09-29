"""Doctrine guard: /mcp and the REST surface must resolve the same token to
the same Principal.user_id.

This matters concretely, not just abstractly: a user mints their personal
access token via the REST surface (POST /tokens, trusted-header auth) and
then presents that same token to the MCP surface on every /mcp call. If the
two surfaces ever extracted identity from a verified token differently, the
token a user minted would resolve to a different user_id depending on which
surface checked it -- silently, since each surface's own tests would still
pass in isolation.

Both surfaces build a Principal from the same claims dict
(VerifiedToken.claims, produced once by PersonalTokenVerifier.verify), so
this test mints one real token and drives each surface's own extraction
logic over the same claims, rather than duplicating what "the same" means.
"""

import unittest.mock

import fastapi
import fastmcp.server.auth as fastmcp_auth

from app.di.providers import auth as auth_provider
from app.identity import service as identity_service
from app.infra.auth import personal_token
from app.infra.rest.auth import resolver
from tests.fakes import in_memory_identity_store


def _request_with_bearer(secret: str) -> fastapi.Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [(b"authorization", f"Bearer {secret}".encode())],
    }
    return fastapi.Request(scope)


class TestCrossSurfaceIdentity:
    async def test_mcp_and_rest_resolve_the_same_token_to_the_same_user_id(
        self,
    ) -> None:
        users = in_memory_identity_store.InMemoryUserStore()
        tokens = in_memory_identity_store.InMemoryPersonalAccessTokenStore()
        identity = identity_service.IdentityService(users)
        token_service = identity_service.PersonalTokenService(
            tokens,
            default_ttl_days=90,
            max_ttl_days=365,
            last_used_throttle_seconds=300,
        )
        verifier = personal_token.PersonalTokenVerifier(token_service, identity)

        user = await identity.get_or_create("a@example.com")
        _, secret = await token_service.mint(user.user_id, "Claude Code")

        # REST: app.infra.rest.auth.resolver.PersonalTokenUserResolver.
        rest_resolver = resolver.PersonalTokenUserResolver(verifier)
        rest_principal = await rest_resolver.resolve(_request_with_bearer(secret))

        # MCP: app.di.providers.auth.AuthProvider.provide_principal, driven off
        # the same VerifiedToken claims via a stubbed fastmcp AccessToken (the
        # shape app.infra.mcp.auth._McpTokenVerifier.verify_token produces).
        verified = await verifier.verify(secret)
        assert verified is not None
        access_token = fastmcp_auth.AccessToken(
            token=secret,
            client_id=str(verified.claims.get("sub", "")),
            scopes=[],
            claims=verified.claims,
        )
        with unittest.mock.patch(
            "app.di.providers.auth.fastmcp_deps.get_access_token",
            return_value=access_token,
        ):
            mcp_principal = auth_provider.AuthProvider().provide_principal(
                unittest.mock.MagicMock()
            )

        assert rest_principal.user_id == mcp_principal.user_id == user.user_id
        assert rest_principal.email == mcp_principal.email == "a@example.com"
