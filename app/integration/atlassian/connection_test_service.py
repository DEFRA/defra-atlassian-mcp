import pydantic
from pydantic import alias_generators

from app.integration.atlassian import client as atlassian_client


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
    def __init__(self, client: atlassian_client.AtlassianClient) -> None:
        self._client = client

    async def test_connection(self, user_id: str) -> AtlassianProfile:
        """Test the user's Atlassian connection by calling GET /me.

        Raises exceptions.AtlassianTokenError if the user is not linked or the
        stored token cannot be refreshed.

        Raises exceptions.AtlassianApiError if Atlassian returns a non-2xx
        response (e.g. the token is revoked or expired).

        Raises exceptions.AtlassianUnavailableError if no response is received
        at all (e.g. Atlassian is unreachable or the request times out).
        """
        payload = await self._client.get_me(user_id)

        return AtlassianProfile(
            account_id=payload.get("account_id"),
            display_name=payload.get("name"),
            email=payload.get("email"),
        )
