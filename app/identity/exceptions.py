class UnknownTokenError(Exception):
    """Raised when no PersonalAccessToken matches a presented secret."""


class TokenExpiredError(Exception):
    """Raised when a presented token's expiry has passed."""


class TokenRevokedError(Exception):
    """Raised when a presented token has been revoked."""


class TokenNotFoundError(Exception):
    """Raised when a token id does not exist or does not belong to the caller."""
