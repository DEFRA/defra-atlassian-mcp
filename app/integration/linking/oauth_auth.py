from typing import Protocol

from app.integration.atlassian import errors, models, ports
from app.integration.linking import models as linking_models

# Written for the MCP caller -- the tools pass AtlassianCredentialsError
# messages through as-is, so they must not carry a user id.
_NOT_LINKED_MESSAGE = (
    "No Atlassian credentials found. Please connect your Atlassian account "
    "in the portal first."
)
_NO_SITE_MESSAGE = "The linked Atlassian account has access to no sites."


class CredentialSource(Protocol):
    """The part of OAuthClient this adapter needs."""

    async def get_valid_credentials(
        self, user_id: str
    ) -> linking_models.AtlassianToken: ...


class OAuthAtlassianAuth:
    """AtlassianAuth for one user's linked OAuth (3LO) account.

    Built per request, bound to the calling user, so nothing downstream of
    it needs to know who the user is. OAuth calls go through Atlassian's API
    gateway, addressed by the site's cloud id, with the user's access token
    as a bearer -- refreshed first by OAuthClient if it is near expiry.
    """

    def __init__(self, user_id: str, oauth: CredentialSource, api_base: str) -> None:
        self._user_id = user_id
        self._oauth = oauth
        self._api_base = api_base.rstrip("/")

    async def authorize(self, product: models.Product) -> ports.RequestAuth:
        try:
            token = await self._oauth.get_valid_credentials(self._user_id)
        except errors.AtlassianCredentialsError as exc:
            raise errors.AtlassianCredentialsError(_NOT_LINKED_MESSAGE) from exc

        if token.cloud_id is None:
            raise errors.AtlassianCredentialsError(_NO_SITE_MESSAGE)

        return ports.RequestAuth(
            base_url=f"{self._api_base}/ex/{product.value}/{token.cloud_id}",
            headers={"Authorization": f"Bearer {token.access_token}"},
        )
