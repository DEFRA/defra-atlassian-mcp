from app.integration.atlassian.errors import (
    AtlassianApiError,
    AtlassianCredentialsError,
    AtlassianUnavailableError,
)

__all__ = [
    "AtlassianApiError",
    "AtlassianCredentialsError",
    "AtlassianTokenError",
    "AtlassianUnavailableError",
    "LinkMismatchError",
    "NoAccessibleSiteError",
    "OAuthStateError",
]

# The old name for AtlassianCredentialsError, kept so existing OAuth call
# sites read naturally. It is the same class, so catching either catches
# both.
AtlassianTokenError = AtlassianCredentialsError


class OAuthStateError(Exception):
    """Raised when an OAuth state token is unknown, already consumed, or
    expired."""


class LinkMismatchError(Exception):
    """Raised when a completed OAuth callback's state was issued for a
    different user than the one completing it."""


class NoAccessibleSiteError(Exception):
    """Raised when a freshly linked account grants access to no Atlassian
    site, so there is no cloud id to address the product APIs with."""
