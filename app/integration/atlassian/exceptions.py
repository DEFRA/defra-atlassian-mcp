class AccessRequestNotFoundError(Exception):
    """Raised when an access request id does not exist."""


class AccessRequestAlreadyDecidedError(Exception):
    """Raised when approving/rejecting a product that is no longer pending."""


class AccessRequestAlreadyOpenError(Exception):
    """Raised when every product a user is asking for is already pending or
    approved on their existing request for that space."""
