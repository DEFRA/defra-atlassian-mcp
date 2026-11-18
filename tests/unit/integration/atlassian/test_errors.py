"""The vendor errors moved from app.integration.linking.exceptions to
app.integration.atlassian.errors so that shared code can raise and catch them
without importing the OAuth linking package. The old names must keep
working, and must be the same classes, or an `except` on one name would miss
an error raised under the other.
"""

import subprocess
import sys

from app.integration.atlassian import errors
from app.integration.linking import exceptions as linking_exceptions


class TestReExports:
    def test_old_names_are_the_same_classes(self):
        assert linking_exceptions.AtlassianApiError is errors.AtlassianApiError
        assert (
            linking_exceptions.AtlassianUnavailableError
            is errors.AtlassianUnavailableError
        )
        assert (
            linking_exceptions.AtlassianTokenError is errors.AtlassianCredentialsError
        )

    def test_api_error_keeps_its_status_code(self):
        err = errors.AtlassianApiError(503)

        assert err.status_code == 503
        assert "503" in str(err)


class TestIsolation:
    def test_importing_errors_does_not_load_the_linking_package(self):
        """Run in a fresh interpreter: this test session has already
        imported the linking package."""
        code = (
            "import sys, app.integration.atlassian.errors; "
            "loaded = [m for m in sys.modules if m.startswith('app.integration.linking')]; "
            "assert not loaded, loaded"
        )

        result = subprocess.run(  # noqa: S603 -- fixed argv, no user input
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
