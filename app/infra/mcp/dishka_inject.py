"""FastMCP integration for Dishka, mirroring `dishka.integrations.fastapi`.

FastMCP exposes no middleware seam that wraps tool execution, so the
`@inject` decorator opens a REQUEST sub-container per invocation
(`manage_scope=True`). The lifespan-scoped container is read from
`ctx.lifespan_context["container"]`, where `ctx` is the `fastmcp.Context`
argument passed by FastMCP to the tool.
"""

import functools
import inspect
import typing
import uuid
from collections.abc import Callable
from typing import Any

import dishka
import fastmcp
from dishka.integrations import base as dishka_base

from app.common import request_context, tracing

_LIFESPAN_CONTAINER_KEY = "container"

__all__ = [
    "FastMCPProvider",
    "inject",
]


class FastMCPProvider(dishka.Provider):
    """Surfaces the FastMCP `Context` and `RequestContext` to Dishka
    providers. Both bindings are populated by `inject`'s `provide_context`
    when a tool is invoked."""

    ctx = dishka.from_context(fastmcp.Context, scope=dishka.Scope.REQUEST)
    req = dishka.from_context(
        request_context.RequestContext, scope=dishka.Scope.REQUEST
    )


def inject(func: Callable[..., Any]) -> Callable[..., Any]:
    """Inject `FromDishka[T]` parameters into a FastMCP tool.

    The wrapped tool must accept a `fastmcp.Context` parameter — this is how
    the integration locates the per-app Dishka container that FastMCP stores
    in `ctx.lifespan_context["container"]`.
    """
    ctx_param_name = _find_context_param(func)
    if ctx_param_name is None:
        msg = (
            f"FastMCP tool {func.__qualname__!r} must accept a "
            "`fastmcp.Context` parameter for dishka injection"
        )
        raise TypeError(msg)

    injected = dishka_base.wrap_injection(
        func=func,
        is_async=True,
        container_getter=_make_container_getter(ctx_param_name),
        manage_scope=True,
        scope=dishka.Scope.REQUEST,
        provide_context=_make_provide_context(ctx_param_name),
    )

    @functools.wraps(injected, updated=())
    async def with_trace(*args: Any, **kwargs: Any) -> Any:
        ctx = _extract_ctx(args, kwargs, ctx_param_name)
        rc = _build_request_context(ctx)
        token = tracing.ctx_trace_id.set(rc.trace_id)
        try:
            return await injected(*args, **kwargs)
        finally:
            tracing.ctx_trace_id.reset(token)

    with_trace.__signature__ = injected.__signature__  # type: ignore[attr-defined]
    with_trace.__annotations__ = injected.__annotations__
    with_trace.__dishka_injected__ = True  # type: ignore[attr-defined]
    return with_trace


def _find_context_param(func: Callable[..., Any]) -> str | None:
    hints = typing.get_type_hints(func, include_extras=True)
    sig = inspect.signature(func)
    for name in sig.parameters:
        if hints.get(name) is fastmcp.Context:
            return name
    return None


def _make_container_getter(
    ctx_param_name: str,
) -> Callable[[tuple[Any, ...], dict[str, Any]], dishka.AsyncContainer]:
    def getter(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dishka.AsyncContainer:
        ctx = _extract_ctx(args, kwargs, ctx_param_name)
        try:
            container: dishka.AsyncContainer = ctx.lifespan_context[
                _LIFESPAN_CONTAINER_KEY
            ]
        except KeyError as exc:
            msg = (
                "FastMCP lifespan did not yield a "
                f"{_LIFESPAN_CONTAINER_KEY!r} entry; the dishka container "
                "must be registered there before tools are invoked."
            )
            raise RuntimeError(msg) from exc
        return container

    return getter


def _make_provide_context(
    ctx_param_name: str,
) -> Callable[[tuple[Any, ...], dict[str, Any]], dict[Any, Any]]:
    def provide(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[Any, Any]:
        ctx = _extract_ctx(args, kwargs, ctx_param_name)
        return {
            fastmcp.Context: ctx,
            request_context.RequestContext: _build_request_context(ctx),
        }

    return provide


def _extract_ctx(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx_param_name: str,
) -> fastmcp.Context:
    ctx: fastmcp.Context | None = kwargs.get(ctx_param_name)
    if ctx is None:
        ctx = next((arg for arg in args if isinstance(arg, fastmcp.Context)), None)
    if ctx is None:
        msg = (
            f"FastMCP tool was invoked without a {ctx_param_name!r} "
            "(fastmcp.Context) argument"
        )
        raise RuntimeError(msg)
    return ctx


def _build_request_context(ctx: fastmcp.Context) -> request_context.RequestContext:
    try:
        trace_id = ctx.request_id
    except (LookupError, ValueError):
        trace_id = str(uuid.uuid4())
    return request_context.RequestContext(trace_id=trace_id)
