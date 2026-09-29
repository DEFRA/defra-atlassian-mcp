from app.integration.linking import exceptions, models


class FakeOAuthClient:
    """Returns a fixed access token per user, bypassing HTTP entirely."""

    def __init__(
        self, default_token: str | None = None, cloud_id: str = "test-cloud-id"
    ) -> None:
        self._token = default_token
        self._cloud_id = cloud_id

    async def get_valid_credentials(self, user_id: str) -> models.AtlassianToken:
        if self._token is None:
            msg = f"No Atlassian token for user {user_id}"
            raise exceptions.AtlassianTokenError(msg)
        return models.AtlassianToken(
            access_token=self._token,
            refresh_token="test-refresh-token",
            cloud_id=self._cloud_id,
        )

    async def get_valid_token(self, user_id: str) -> str:
        token = await self.get_valid_credentials(user_id)
        return token.access_token
