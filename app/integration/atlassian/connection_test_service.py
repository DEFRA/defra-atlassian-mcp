import httpx2
import pydantic
from pydantic import alias_generators

from app.integration.atlassian import client as atlassian_client
from app.integration.linking import oauth_client


class AtlassianProfile(pydantic.BaseModel):
    """The linked account, as the portal renders it. The portal prefers
    ``displayName`` and falls back to ``email``, so both are passed through
    even when Atlassian only fills one."""

    model_config = pydantic.ConfigDict(
        alias_generator=alias_generators.to_camel, populate_by_name=True
    )

    account_id: str | None = None
    display_name: str | None = None
    email: str | None = None


class AtlassianConnectionTestService:
    """Checks a user's linked OAuth account by calling Atlassian's ``/me``.

    HTTP-only and OAuth-specific: ``/me`` hangs off the API gateway root, not
    a product, so it does not go through AtlassianClient.
    """

    def __init__(
        self,
        http: httpx2.AsyncClient,
        oauth: oauth_client.OAuthClient,
        api_base: str,
    ) -> None:
        self._http = http
        self._oauth = oauth
        self._api_base = api_base.rstrip("/")

    async def test_connection(self, user_id: str) -> AtlassianProfile:
        """Test the user's Atlassian connection by calling GET /me.

        Raises errors.AtlassianCredentialsError if the user is not linked or the
        stored token cannot be refreshed.

        Raises errors.AtlassianApiError if Atlassian returns a non-2xx
        response (e.g. the token is revoked or expired).

        Raises errors.AtlassianUnavailableError if no response is received
        at all (e.g. Atlassian is unreachable or the request times out).
        """
        access_token = await self._oauth.get_valid_token(user_id)
        payload = await atlassian_client.get_json(
            self._http,
            f"{self._api_base}/me",
            {"Authorization": f"Bearer {access_token}"},
        )

        return AtlassianProfile(
            account_id=payload.get("account_id"),
            display_name=payload.get("name"),
            email=payload.get("email"),
        )
