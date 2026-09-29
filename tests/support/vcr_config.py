"""VCR scrubbing (see docs/python-testing-standard.md §4.3).

Header filtering alone is not enough: the Atlassian OAuth token endpoint carries
the client secret and the authorization code in a form-encoded *body*, and
returns `access_token`/`refresh_token` in a JSON *response body*. Scrub
sensitive headers, form fields, query parameters, and JSON keys at any
depth, in both directions.

`before_record_response` also runs on *playback*, so it must preserve the
body's type exactly -- handing httpx2 a `str` where the cassette stored
`bytes` fails deep in the transport with an unhelpful `TypeError`.
"""

import json
from typing import Any

PLACEHOLDER = "[FILTERED]"

SENSITIVE_HEADERS = ["authorization", "Authorization"]
# Form-encoded body fields (application/x-www-form-urlencoded) -- vcrpy
# decodes, filters and re-encodes these itself via filter_post_data_parameters.
SENSITIVE_POST_PARAMS = ["client_secret", "code", "refresh_token"]
SENSITIVE_QUERY_PARAMS = ["client_secret", "code", "state"]
# JSON keys scrubbed at any depth in a JSON response body.
SENSITIVE_JSON_KEYS = {"access_token", "refresh_token", "client_secret"}


def _scrub_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (PLACEHOLDER if key in SENSITIVE_JSON_KEYS else _scrub_json_value(val))
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_scrub_json_value(item) for item in value]
    return value


def before_record_response(response: dict[str, Any]) -> dict[str, Any]:
    """Scrub sensitive JSON keys at any depth in the response body.

    Runs on both recording and playback, so the body's str/bytes type is
    preserved exactly -- httpx2 rejects the wrong type deep in the transport.
    """
    body = response.get("body", {})
    raw = body.get("string")
    if raw is None:
        return response

    is_bytes = isinstance(raw, bytes)
    text = raw.decode() if is_bytes else raw
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return response

    scrubbed_text = json.dumps(_scrub_json_value(payload))
    body["string"] = scrubbed_text.encode() if is_bytes else scrubbed_text
    return response
