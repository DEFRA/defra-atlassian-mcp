class AtlassianTokenError(Exception):
    """Raised when no valid Atlassian access token is available for a user."""


class OAuthStateError(Exception):
    """Raised when an OAuth state token is unknown, already consumed, or
    expired."""


class LinkMismatchError(Exception):
    """Raised when a completed OAuth callback's state was issued for a
    different user than the one completing it."""


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


class NoAccessibleSiteError(Exception):
    """Raised when a freshly linked account grants access to no Atlassian
    site, so there is no cloud id to address the product APIs with."""
