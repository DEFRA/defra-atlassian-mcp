"""Binds the app's own TokenVerifier port to FastMCP's auth machinery for
the /mcp surface — the only module in the app that imports
fastmcp.server.auth.
"""

import dishka
import fastmcp.server.auth as fastmcp_auth

from app.auth import verifier as verifier_port


class _McpTokenVerifier(fastmcp_auth.TokenVerifier):
    """Resolves app.auth.verifier.TokenVerifier from the Dishka container on
    every call, rather than once at construction time. build_mcp_app() runs
    before the container's lifespan has opened its APP-scoped providers (the
    Mongo client among them), so nothing can be resolved eagerly here — only
    once real requests start arriving is the container guaranteed to be
    entered.
    """

    def __init__(self, container: dishka.AsyncContainer) -> None:
        super().__init__()
        self._container = container

    async def verify_token(self, token: str) -> fastmcp_auth.AccessToken | None:
        inner = await self._container.get(verifier_port.TokenVerifier)
        verified = await inner.verify(token)
        if verified is None:
            return None

        return fastmcp_auth.AccessToken(
            token=token,
            client_id=str(verified.claims.get("sub", "")),
            scopes=[],
            claims=verified.claims,
        )


def build_auth_provider(
    container: dishka.AsyncContainer,
) -> fastmcp_auth.AuthProvider:
    return _McpTokenVerifier(container)
