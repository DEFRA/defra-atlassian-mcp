"""Holds the boundary between code shared with the stdio entry point and
HTTP-only code.

There is no directory split: HTTP-only modules sit beside shared ones (e.g.
atlassian/mongo_store.py next to atlassian/guard.py). Because app/ has no
__init__.py files, a module is only loaded if something names it. So the
boundary is exactly the static import closure of app/entrypoints/stdio.py,
which this walks from source with ast -- independent of what the test
session has already imported -- and fails if it reaches anything HTTP-only.

The runtime counterpart (install without the http extra, import, check
sys.modules) runs as a separate CI job.
"""

import ast
import pathlib

_REPO = pathlib.Path(__file__).resolve().parents[2]
_ENTRY = "app.entrypoints.stdio"

_FORBIDDEN_THIRD_PARTY = {"pymongo", "bson", "fastapi", "uvicorn", "ecs_logging"}
_FORBIDDEN_APP_PREFIXES = (
    "app.identity",
    "app.integration.linking",
    "app.infra.rest",
    "app.infra.mcp.auth",
    "app.infra.mcp.http_tools",
    "app.config.http",
    "app.di.container",
    "app.di.providers.auth",
    "app.di.providers.identity",
    "app.di.providers.infrastructure",
    "app.di.providers.integration",
    "app.di.providers.request_scope",
    "app.di.providers.settings",
    "app.common.tracing",
    "app.common.mongo",
    "app.auth",
    "app.health",
    "app.entrypoints.http",
)


def _module_path(name: str) -> pathlib.Path | None:
    candidate = _REPO.joinpath(*name.split("."))
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    return None


def _imports_of(name: str) -> set[str]:
    """Fully qualified names this module imports. For ``from a.b import c``
    both ``a.b`` and ``a.b.c`` are returned; the caller keeps whichever is a
    real module."""
    path = _module_path(name)
    if path is None:
        return set()
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _closure() -> tuple[set[str], set[str]]:
    """(app modules reached, third-party top-level packages reached)."""
    seen: set[str] = set()
    third_party: set[str] = set()
    stack = [_ENTRY]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        for imported in _imports_of(name):
            if imported.split(".")[0] != "app":
                third_party.add(imported.split(".")[0])
            elif _module_path(imported) is not None:
                stack.append(imported)
    return seen, third_party


def test_the_closure_walk_finds_the_core():
    """Guards against the walk silently finding nothing (a moved entry
    point, a broken resolver) and the test below passing vacuously."""
    modules, _ = _closure()

    assert {
        "app.entrypoints.stdio",
        "app.di.stdio_container",
        "app.infra.mcp.tools",
        "app.integration.atlassian.jira.service",
        "app.integration.atlassian.client",
        "app.config.stdio",
    } <= modules


def test_stdio_reaches_no_http_only_module():
    modules, _ = _closure()

    violations = sorted(m for m in modules if m.startswith(_FORBIDDEN_APP_PREFIXES))
    violations += sorted(m for m in modules if m.endswith("mongo_store"))
    assert not violations, (
        f"{_ENTRY} reaches HTTP-only modules: {violations}. Shared code must "
        "not import them; move the dependency behind a port or into an "
        "HTTP-only module."
    )


def test_stdio_imports_no_http_only_package():
    _, third_party = _closure()

    assert not (third_party & _FORBIDDEN_THIRD_PARTY), sorted(
        third_party & _FORBIDDEN_THIRD_PARTY
    )
