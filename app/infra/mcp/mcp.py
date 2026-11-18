import contextlib
from collections.abc import AsyncGenerator
from typing import Any

import dishka
import fastmcp
import fastmcp.server.auth as fastmcp_auth


def build_server(
    name: str,
    container: dishka.AsyncContainer,
    *,
    auth: fastmcp_auth.AuthProvider | None = None,
) -> fastmcp.FastMCP:
    """Build the FastMCP server shared by both entry points.

    The Dishka container is handed to tools through the lifespan context
    (see app.infra.mcp.dishka_inject). ``auth`` is the transport auth
    provider: the HTTP entry point passes its personal-access-token
    verifier; the stdio entry point passes nothing, since the process is
    started by, and talks only to, the local user's MCP client.
    """

    @contextlib.asynccontextmanager
    async def _lifespan(_server: fastmcp.FastMCP) -> AsyncGenerator[dict[str, Any]]:
        yield {"container": container}

    return fastmcp.FastMCP(name, lifespan=_lifespan, auth=auth)
