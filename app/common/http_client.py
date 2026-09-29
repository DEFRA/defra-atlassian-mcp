import logging
import ssl

import httpx2
import truststore

from app.common import tracing

logger = logging.getLogger(__name__)


def _create_ssl_context() -> ssl.SSLContext:
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


async def async_hook_request_tracing(request: httpx2.Request) -> None:
    trace_id = tracing.ctx_trace_id.get(None)
    tracing_header = tracing.ctx_tracing_header.get(None)
    if trace_id and tracing_header:
        request.headers[tracing_header] = trace_id


def hook_request_tracing(request: httpx2.Request) -> None:
    trace_id = tracing.ctx_trace_id.get(None)
    tracing_header = tracing.ctx_tracing_header.get(None)
    if trace_id and tracing_header:
        request.headers[tracing_header] = trace_id


def create_async_client(
    *,
    tracing_header: str | None = None,
    trace_id: str | None = None,
    proxy: str | None = None,
    request_timeout: int = 30,
) -> httpx2.AsyncClient:
    headers = {tracing_header: trace_id} if tracing_header and trace_id else None
    return httpx2.AsyncClient(
        timeout=request_timeout,
        headers=headers,
        proxy=proxy,
        verify=_create_ssl_context(),
        event_hooks={"request": [async_hook_request_tracing]},
    )


def create_client(
    *,
    tracing_header: str | None = None,
    trace_id: str | None = None,
    proxy: str | None = None,
    request_timeout: int = 30,
) -> httpx2.Client:
    headers = {tracing_header: trace_id} if tracing_header and trace_id else None
    return httpx2.Client(
        timeout=request_timeout,
        headers=headers,
        proxy=proxy,
        verify=_create_ssl_context(),
        event_hooks={"request": [hook_request_tracing]},
    )
