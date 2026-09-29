"""Doctrine guard: there must be no signature-verification bypass anywhere
in the caller-identity path.

The old DEV_AUTH_ENABLED flag disabled JWT signature checking outright — a
full impersonation hole on /mcp and every REST route, one boolean away from
production, and it shipped with a "never enable in production" comment as
its only real defence. atlassian-mcp no longer verifies signed tokens at all for
caller identity (it mints its own opaque personal access tokens and looks
them up), so there is no longer any code path with a signature check to
skip. Keep it that way mechanically: this test — not a review checklist —
is what stops it coming back.

Scoped to the caller-identity modules only, not all of app/:
app/integration/linking/oauth_client.py legitimately reads
options={"verify_signature": False} when peeking at the *vendor's* (Atlassian's)
own OAuth access token to check its expiry — a different system (this
server acting as an OAuth client of Atlassian), not a decision about who the
caller is, so it is out of scope for this guard.
"""

import pathlib

import pytest

from app import config as app_config

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_IDENTITY_AUTH_DIRS = (
    _REPO_ROOT / "app" / "auth",
    _REPO_ROOT / "app" / "identity",
    _REPO_ROOT / "app" / "infra" / "auth",
    _REPO_ROOT / "app" / "infra" / "mcp",
    _REPO_ROOT / "app" / "infra" / "rest" / "auth",
)


def _identity_auth_files() -> list[pathlib.Path]:
    return sorted(
        path for directory in _IDENTITY_AUTH_DIRS for path in directory.rglob("*.py")
    )


class TestNoSignatureVerificationBypass:
    def test_verify_signature_appears_nowhere_in_the_identity_path(self) -> None:
        hits = [
            str(path.relative_to(_REPO_ROOT))
            for path in _identity_auth_files()
            if "verify_signature" in path.read_text()
        ]
        assert not hits, f"'verify_signature' found in: {hits}"

    def test_app_config_has_no_dev_auth_bypass_fields(self) -> None:
        forbidden = {"dev_auth_enabled", "dev_auth_jwt_secret"}
        present = forbidden & set(app_config.AppConfig.model_fields)
        assert not present, f"AppConfig still declares bypass field(s): {present}"

    @pytest.mark.parametrize("needle", ['algorithms=["none"]', "alg: none", "'none'"])
    def test_no_unsigned_alg_none_handling_in_the_identity_path(
        self, needle: str
    ) -> None:
        hits = [
            str(path.relative_to(_REPO_ROOT))
            for path in _identity_auth_files()
            if needle in path.read_text()
        ]
        assert not hits, f"{needle!r} found in: {hits}"

    def test_identity_auth_dirs_are_not_empty(self) -> None:
        """Guards against the checks above silently collecting zero files if
        these directories are ever moved/renamed."""
        assert len(_identity_auth_files()) >= 5
