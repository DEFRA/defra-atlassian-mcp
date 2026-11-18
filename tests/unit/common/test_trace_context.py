"""The trace ContextVars live in app.common.trace_context so that modules
shared with the stdio entry point can use them without importing the
FastAPI middleware in app.common.tracing, which pulls in fastapi and
the HTTP settings (app.config.http).

starlette is not checked: fastmcp itself depends on it.
"""

import subprocess
import sys

import pytest

from app.common import trace_context, tracing

_SHARED_MODULES = (
    "app.common.trace_context",
    "app.common.http_client",
    "app.common.log_utils",
    "app.infra.mcp.dishka_inject",
)
_FORBIDDEN = ("fastapi", "app.config.http", "app.common.tracing")


@pytest.mark.parametrize("module", _SHARED_MODULES)
def test_shared_module_does_not_load_fastapi_or_the_http_config(module):
    """Run in a fresh interpreter: this test session has already imported
    everything."""
    code = (
        f"import sys, {module}; "
        f"loaded = [m for m in {_FORBIDDEN!r} if m in sys.modules]; "
        "assert not loaded, loaded"
    )

    result = subprocess.run(  # noqa: S603 -- fixed argv, no user input
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_tracing_re_exports_the_same_context_vars():
    """The middleware sets the vars through app.common.tracing and the log
    filter reads them through app.common.trace_context, so they must be the
    same objects."""
    assert tracing.ctx_trace_id is trace_context.ctx_trace_id
    assert tracing.ctx_tracing_header is trace_context.ctx_tracing_header
    assert tracing.ctx_request is trace_context.ctx_request
    assert tracing.ctx_response is trace_context.ctx_response
