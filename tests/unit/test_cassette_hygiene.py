"""Independent proof that VCR scrubbing (tests/support/vcr_config.py)
actually reached the committed cassettes (see
docs/python-testing-standard.md §4.3) -- re-reads the raw YAML from disk
rather than trusting the scrubber's own claim, so weakening the scrubber
does not also weaken this check. Carries an anti-vacuity test so it cannot
pass by silently matching zero files.
"""

import pathlib
import re

import pytest

_CASSETTES_DIR = pathlib.Path(__file__).parent.parent / "cassettes"

# A JWT-shaped string: header.payload.signature, base64url segments.
_JWT_PATTERN = re.compile(
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"
)

# Form/query fields that must appear only as `name=[FILTERED]`, never with a
# real-looking value -- kept in sync with vcr_config.SENSITIVE_POST_PARAMS.
_SENSITIVE_FIELDS = ("client_secret", "code", "refresh_token")


def _cassette_paths() -> list[pathlib.Path]:
    return sorted(_CASSETTES_DIR.glob("*.yaml"))


class TestCassetteHygiene:
    def test_cassettes_directory_is_not_empty(self):
        """If this ever collects zero cassettes, every check below passes
        for the wrong reason -- there being nothing to check."""
        assert _cassette_paths()

    @pytest.mark.parametrize("path", _cassette_paths(), ids=lambda p: p.name)
    def test_cassette_has_no_jwt_shaped_secret(self, path: pathlib.Path) -> None:
        text = path.read_text()

        match = _JWT_PATTERN.search(text)
        assert match is None, (
            f"{path.name} contains a JWT-shaped string "
            f"({match.group() if match else ''}) -- access_token/refresh_token "
            "must be scrubbed by before_record_response, not left in the recording."
        )

    @pytest.mark.parametrize("path", _cassette_paths(), ids=lambda p: p.name)
    @pytest.mark.parametrize("field", _SENSITIVE_FIELDS)
    def test_cassette_sensitive_fields_are_filtered(
        self, path: pathlib.Path, field: str
    ) -> None:
        text = path.read_text()

        for match in re.finditer(rf"{field}=([^&\s'\"]+)", text):
            assert match.group(1) == "[FILTERED]", (
                f"{path.name} has an unfiltered {field} value -- "
                "filter_post_data_parameters/filter_query_parameters must cover it."
            )
