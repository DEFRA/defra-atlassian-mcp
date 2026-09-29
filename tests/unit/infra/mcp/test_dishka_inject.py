import unittest.mock

import dishka
import fastmcp
import pytest

from app.common import request_context
from app.infra.mcp import dishka_inject


class _DummyService:
    def __init__(self, label: str = "real") -> None:
        self.label = label


class _DummyProvider(dishka.Provider):
    scope = dishka.Scope.APP

    @dishka.provide
    def service(self) -> _DummyService:
        return _DummyService(label="real")


class _TraceEchoProvider(dishka.Provider):
    """REQUEST-scoped provider that consumes the from_context RequestContext."""

    scope = dishka.Scope.REQUEST

    @dishka.provide
    def trace(self, rc: request_context.RequestContext) -> str:
        return rc.trace_id


def _make_ctx(
    container: dishka.AsyncContainer, request_id: str = "trace-123"
) -> fastmcp.Context:
    ctx = unittest.mock.MagicMock(spec=fastmcp.Context)
    ctx.lifespan_context = {"container": container}
    ctx.request_id = request_id
    return ctx


@pytest.fixture
async def container() -> dishka.AsyncContainer:
    async with dishka.make_async_container(
        _DummyProvider(),
        _TraceEchoProvider(),
        dishka_inject.FastMCPProvider(),
    ) as built:
        yield built


class TestInject:
    async def test_supplies_from_dishka_dependency(
        self, container: dishka.AsyncContainer
    ) -> None:
        @dishka_inject.inject
        async def tool(
            ctx: fastmcp.Context,  # noqa: ARG001  # required by decorator contract
            service: dishka.FromDishka[_DummyService],
        ) -> str:
            return service.label

        result = await tool(ctx=_make_ctx(container))

        assert result == "real"

    def test_removes_from_dishka_params_from_signature(self) -> None:
        @dishka_inject.inject
        async def tool(
            issue_key: str,
            ctx: fastmcp.Context,  # noqa: ARG001  # required by decorator contract
            service: dishka.FromDishka[_DummyService],
        ) -> str:
            return f"{issue_key}:{service.label}"

        params = list(tool.__signature__.parameters)

        assert params == ["issue_key", "ctx"]

    async def test_propagates_request_id_into_request_context(
        self, container: dishka.AsyncContainer
    ) -> None:
        @dishka_inject.inject
        async def tool(
            ctx: fastmcp.Context,  # noqa: ARG001  # required by decorator contract
            trace: dishka.FromDishka[str],
        ) -> str:
            return trace

        result = await tool(ctx=_make_ctx(container, request_id="abc-789"))

        assert result == "abc-789"

    async def test_finds_context_passed_positionally(
        self, container: dishka.AsyncContainer
    ) -> None:
        @dishka_inject.inject
        async def tool(
            ctx: fastmcp.Context,  # noqa: ARG001  # required by decorator contract
            service: dishka.FromDishka[_DummyService],
        ) -> str:
            return service.label

        result = await tool(_make_ctx(container))

        assert result == "real"

    def test_raises_when_no_context_param(self) -> None:
        async def tool(service: dishka.FromDishka[_DummyService]) -> str:
            return service.label

        with pytest.raises(TypeError, match="fastmcp.Context"):
            dishka_inject.inject(tool)

    async def test_raises_when_lifespan_missing_container(self) -> None:
        @dishka_inject.inject
        async def tool(
            ctx: fastmcp.Context,  # noqa: ARG001  # required by decorator contract
            service: dishka.FromDishka[_DummyService],
        ) -> str:
            return service.label

        bad_ctx = unittest.mock.MagicMock(spec=fastmcp.Context)
        bad_ctx.lifespan_context = {}

        with pytest.raises(RuntimeError, match="container"):
            await tool(ctx=bad_ctx)

    async def test_opens_and_closes_request_subscope(
        self, container: dishka.AsyncContainer
    ) -> None:
        """Each tool invocation should resolve trace via REQUEST scope, so
        two invocations with different request_ids must see their own
        trace_id."""

        @dishka_inject.inject
        async def tool(
            ctx: fastmcp.Context,  # noqa: ARG001  # required by decorator contract
            trace: dishka.FromDishka[str],
        ) -> str:
            return trace

        first = await tool(ctx=_make_ctx(container, request_id="req-1"))
        second = await tool(ctx=_make_ctx(container, request_id="req-2"))

        assert (first, second) == ("req-1", "req-2")
