import datetime

import pydantic


class AtlassianToken(pydantic.BaseModel):
    """A user's stored Atlassian OAuth credentials.

    ``cloud_id`` is the id of the Atlassian site the token grants access to,
    resolved once at link time from ``/oauth/token/accessible-resources``. It
    is not part of the OAuth response, so a refresh carries the previously
    resolved value forward rather than re-resolving it.
    """

    access_token: str
    refresh_token: str
    expires_at: datetime.datetime | None = None
    cloud_id: str | None = None


class OAuthState(pydantic.BaseModel):
    user_id: str
    code_verifier: str
    expires_at: datetime.datetime


class IssuedState(pydantic.BaseModel):
    """What OAuthStateStore.issue() hands back publicly. The code_verifier
    itself never leaves the store -- only its derived code_challenge goes
    into the authorization URL."""

    state: str
    code_challenge: str


class AtlassianConnectionStatus(pydantic.BaseModel):
    linked: bool
    access_token_expires_at: datetime.datetime | None = None
