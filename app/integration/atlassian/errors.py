"""Vendor errors raised by any Atlassian call, whatever the credential type.

They live here rather than in app.integration.linking because they are not
about OAuth: the Atlassian client and the MCP tools raise and catch them for
API-token calls too. app.integration.linking.exceptions re-exports them under
their old names, and keeps the errors that only the OAuth linking flow
raises.
"""


class AtlassianCredentialsError(Exception):
    """Raised when no usable Atlassian credentials are available for a call
    (for OAuth, the user has not linked an account or the stored token
    cannot be refreshed)."""


class AtlassianApiError(Exception):
    """Raised when the Atlassian API returns a non-2xx response.

    Wraps the underlying httpx2.HTTPStatusError so callers never see raw vendor
    URLs, headers, or response bodies escape to a REST client or an LLM tool
    caller.
    """

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Atlassian API request failed with status {status_code}.")


class AtlassianUnavailableError(Exception):
    """Raised when a request to the Atlassian API fails before any response is
    received (e.g. Atlassian is unreachable, DNS resolution fails, or the
    connection times out).

    Wraps the underlying httpx2.RequestError, distinct from AtlassianApiError
    which means Atlassian *did* respond, just with a non-2xx status.
    """
