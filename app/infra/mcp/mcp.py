import contextlib
from collections.abc import AsyncGenerator
from typing import Any

import dishka
import fastmcp

from app import config as app_config
from app.infra.mcp import auth


def build_mcp_app(
    container: dishka.AsyncContainer, cfg: app_config.AppConfig
) -> fastmcp.FastMCP:
    auth_provider = auth.build_auth_provider(container)

    @contextlib.asynccontextmanager
    async def _lifespan(_server: fastmcp.FastMCP) -> AsyncGenerator[dict[str, Any]]:
        yield {"container": container}

    return fastmcp.FastMCP(cfg.server_name, lifespan=_lifespan, auth=auth_provider)
