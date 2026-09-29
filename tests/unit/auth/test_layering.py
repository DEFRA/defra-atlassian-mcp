"""Doctrine guard: app/auth/ must stay IdP/framework-agnostic.

app.auth defines the TokenVerifier port and the Principal shape that both
/mcp and the REST surface converge on. If it starts importing FastMCP,
FastAPI, Dishka, or an Azure package, the seam is gone and swapping how a
token is verified means editing this package instead of one adapter module.
This was violated once already (the old JwtTokenVerifier subclassed
fastmcp.server.auth.TokenVerifier directly) — enforce it mechanically rather
than relying on review to catch it again.
"""

import ast
import pathlib

import pytest

_AUTH_DIR = pathlib.Path(__file__).resolve().parents[3] / "app" / "auth"
_FORBIDDEN_ROOTS = ("fastmcp", "fastapi", "dishka", "azure", "starlette")


def _imported_roots(source: str) -> set[str]:
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _auth_module_paths() -> list[pathlib.Path]:
    return sorted(_AUTH_DIR.glob("*.py"))


class TestAuthModulesStayFrameworkAgnostic:
    @pytest.mark.parametrize("path", _auth_module_paths(), ids=lambda p: p.name)
    def test_module_imports_no_framework_or_idp_package(
        self, path: pathlib.Path
    ) -> None:
        roots = _imported_roots(path.read_text())
        violations = roots & set(_FORBIDDEN_ROOTS)
        assert not violations, (
            f"{path.relative_to(_AUTH_DIR.parents[1])} imports {violations} — "
            "app/auth/ must stay framework/IdP-agnostic; bind concrete "
            "providers in an adapter under app/infra/ instead."
        )

    def test_auth_dir_is_not_empty(self) -> None:
        """Guards against the parametrised test above silently collecting
        zero cases if the directory is ever moved/renamed."""
        assert len(_auth_module_paths()) >= 2
