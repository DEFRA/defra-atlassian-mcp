import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import dishka
import fastapi
from starlette import responses
from starlette.middleware import base
from starlette.types import ASGIApp, Receive, Scope, Send

from app import config as app_config
from app.common import request_context
from app.common.trace_context import (
    ctx_request,
    ctx_response,
    ctx_trace_id,
    ctx_tracing_header,
)

__all__ = [
    "REQUEST_CONTEXT_SCOPE_KEY",
    "ContainerMiddleware",
    "TraceIdMiddleware",
    "ctx_request",
    "ctx_response",
    "ctx_trace_id",
    "ctx_tracing_header",
]

logger = logging.getLogger(__name__)

# The ContextVars are defined in app.common.trace_context, which has no
# fastapi import; they are re-exported here for the middleware below and for
# existing callers.

REQUEST_CONTEXT_SCOPE_KEY = "request_context"


class TraceIdMiddleware(base.BaseHTTPMiddleware):
    """Extracts the trace header, populates logging ContextVars, and stashes
    a `RequestContext` on the ASGI scope for the container middleware to pick
    up."""

    def __init__(self, app: ASGIApp, cfg: app_config.AppConfig, **kwargs: Any) -> None:
        super().__init__(app, **kwargs)
        self._tracing_header = cfg.tracing_header

    async def dispatch(
        self,
        request: fastapi.Request,
        call_next: Callable[[fastapi.Request], Awaitable[responses.Response]],
    ) -> responses.Response:
        trace_id = request.headers.get(self._tracing_header) or str(uuid.uuid4())
        ctx_trace_id.set(trace_id)
        ctx_tracing_header.set(self._tracing_header)
        ctx_request.set({"url": str(request.url), "method": request.method})

        rc = request_context.RequestContext(
            trace_id=trace_id,
            method=request.method,
            url=str(request.url),
        )
        request.scope[REQUEST_CONTEXT_SCOPE_KEY] = rc

        response = await call_next(request)
        ctx_response.set({"status_code": response.status_code})
        return response


class ContainerMiddleware:
    """Replacement for `dishka_fastapi.ContainerMiddleware` that also
    surfaces `RequestContext` (stashed on the ASGI scope by
    `TraceIdMiddleware`) into the REQUEST sub-container's context dict."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = fastapi.Request(scope, receive, send)
        rc = scope.get(REQUEST_CONTEXT_SCOPE_KEY)
        if rc is None:
            msg = (
                "ContainerMiddleware ran without RequestContext on scope — "
                "TraceIdMiddleware must be configured outside this middleware."
            )
            raise RuntimeError(msg)

        container: dishka.AsyncContainer = request.app.state.dishka_container
        context: dict[Any, Any] = {
            fastapi.Request: request,
            request_context.RequestContext: rc,
        }
        async with container(context, scope=dishka.Scope.REQUEST) as sub:
            request.state.dishka_container = sub
            await self.app(scope, receive, send)
