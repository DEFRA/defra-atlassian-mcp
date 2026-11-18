"""app/infra/mcp/tools.py is registered by the stdio entry point too, so it
must not import anything HTTP-only. AST check, so it holds regardless of
what this test session has already imported."""

import ast
import pathlib

_TOOLS = (
    pathlib.Path(__file__).resolve().parents[4] / "app" / "infra" / "mcp" / "tools.py"
)
_FORBIDDEN_PREFIXES = (
    "app.auth",
    "app.identity",
    "app.integration.linking",
    "app.integration.atlassian.access_request_service",
    "app.integration.atlassian.approved_requests_source",
    "app.infra.rest",
    "app.config.http",
    "fastapi",
    "pymongo",
)


def _imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_shared_tools_import_nothing_http_only():
    modules = _imported_modules(_TOOLS.read_text())

    violations = sorted(m for m in modules if m.startswith(_FORBIDDEN_PREFIXES))
    assert not violations, violations
