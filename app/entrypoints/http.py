import collections
import contextlib
import logging

import dishka
import fastapi
import fastmcp.utilities.lifespan as fastmcp_lifespan
import uvicorn

from app import config as app_config
from app.common import tracing
from app.di import container as di_container
from app.health import router as health_router
from app.infra.mcp import mcp
from app.infra.mcp import tools as atlassian_tools
from app.infra.rest import admin_router, token_router
from app.infra.rest import approval_router as atlassian_approval_router
from app.infra.rest import linking_router as atlassian_linking_router

logger = logging.getLogger(__name__)


def create_app(
    cfg: app_config.AppConfig,
    *,
    container: dishka.AsyncContainer | None = None,
) -> fastapi.FastAPI:
    container = container or di_container.build_async_container()
    mcp_fastmcp = mcp.build_mcp_app(container, cfg)
    atlassian_tools.register_tools(mcp_fastmcp)
    mcp_app = mcp_fastmcp.http_app(path="/")

    @contextlib.asynccontextmanager
    async def lifespan(_: fastapi.FastAPI) -> collections.abc.AsyncGenerator[None]:
        async with container:
            _.state.dishka_container = container
            yield

    fastapi_app = fastapi.FastAPI(
        lifespan=fastmcp_lifespan.combine_lifespans(lifespan, mcp_app.lifespan)
    )

    fastapi_app.mount("/mcp", mcp_app)

    fastapi_app.add_middleware(tracing.ContainerMiddleware)
    # starlette's `_MiddlewareFactory` protocol expects its own more
    # permissive, private ASGI-app alias rather than `starlette.types.ASGIApp`
    # (see the comment in `starlette.middleware`), so a correctly-typed `app`
    # param here still reads as a mismatch to mypy.
    fastapi_app.add_middleware(tracing.TraceIdMiddleware, cfg=cfg)  # type: ignore[arg-type]
    fastapi_app.include_router(health_router.router)
    fastapi_app.include_router(atlassian_linking_router.router, prefix="/linking")
    fastapi_app.include_router(atlassian_approval_router.router, prefix="/approvals")
    fastapi_app.include_router(token_router.router, prefix="/tokens")
    fastapi_app.include_router(admin_router.router, prefix="/admin")

    return fastapi_app


def create_app_factory() -> fastapi.FastAPI:  # pragma: no cover
    """Entrypoint for uvicorn's reloader, which needs an import string (not a
    live app instance) so it can rebuild the app in each reloaded worker."""
    with di_container.build_sync_container() as _container:
        cfg = _container.get(app_config.AppConfig)

    return create_app(cfg)


def main() -> None:  # pragma: no cover
    with di_container.build_sync_container() as _container:
        cfg = _container.get(app_config.AppConfig)

    uvicorn.run(
        "app.entrypoints.http:create_app_factory",
        host=cfg.host,
        port=cfg.port,
        log_config=cfg.log_config,
        reload=cfg.python_env == "development",
        factory=True,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
