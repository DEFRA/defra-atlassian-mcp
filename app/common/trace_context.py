"""Per-request trace ContextVars, with no web-framework imports.

These exist solely so the logging filter in
`app.common.log_utils.ExtraFieldsFilter` can enrich log records, and so the
outbound httpx hook in `app.common.http_client` can forward the trace id.
They are NOT a back-channel for cross-service state -- every other consumer
should depend on RequestContext via Dishka instead.

They live apart from `app.common.tracing` (the FastAPI middleware that sets
them for HTTP requests) so that code shared with the stdio entry point --
the MCP injection decorator, the HTTP client, the log filter -- can use them
without importing fastapi or starlette.
"""

import contextvars

ctx_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id")
ctx_tracing_header: contextvars.ContextVar[str] = contextvars.ContextVar(
    "tracing_header"
)
ctx_request: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "request"
)
ctx_response: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "response"
)
