import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class RequestContext:
    """Per-request metadata available inside the REQUEST scope.

    Constructed by the FastAPI middleware and the FastMCP `@inject` decorator;
    consumed by REQUEST-scoped providers (e.g. the per-request httpx2 client)
    via `dishka.from_context`.
    """

    trace_id: str
    method: str | None = None
    url: str | None = None
