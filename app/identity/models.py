import datetime
import enum

import pydantic


class TokenStatus(enum.StrEnum):
    """A token's lifecycle state, derived rather than stored — revocation and
    expiry are already recorded as timestamps, and a second stored copy could
    disagree with them."""

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class User(pydantic.BaseModel):
    """A caller identity, keyed by the portal-asserted email address itself.

    This server does not mint its own identifier: ``user_id`` is the email
    taken verbatim from the trusted header, so a repeat visit from the same
    address resolves back to the same record rather than creating a
    duplicate. ``email`` is kept as a separate field, identical to
    ``user_id`` by construction, only so callers reading claims (see
    app.infra.auth.personal_token) don't have to know the two collapsed.
    """

    user_id: str
    email: str
    created_at: datetime.datetime


class PersonalAccessToken(pydantic.BaseModel):
    """A minted personal access token record.

    The plaintext secret is never stored — only its SHA-256 hash — so there
    is no code path that can return it after the mint response.
    """

    id: str
    user_id: str
    token_hash: str
    prefix: str
    label: str
    created_at: datetime.datetime
    expires_at: datetime.datetime
    last_used_at: datetime.datetime | None = None
    revoked_at: datetime.datetime | None = None

    @property
    def is_active(self) -> bool:
        now = datetime.datetime.now(datetime.UTC)
        return self.revoked_at is None and self.expires_at > now

    @property
    def status(self) -> TokenStatus:
        if self.revoked_at is not None:
            return TokenStatus.REVOKED
        if self.expires_at <= datetime.datetime.now(datetime.UTC):
            return TokenStatus.EXPIRED
        return TokenStatus.ACTIVE
