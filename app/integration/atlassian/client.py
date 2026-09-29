from typing import Any

import httpx2

from app import config as app_config
from app.integration.atlassian import models
from app.integration.linking import exceptions, oauth_client

_PRODUCT_PATH_SEGMENT = {
    models.Product.JIRA: "jira",
    models.Product.CONFLUENCE: "confluence",
}


class AtlassianClient:
    """The single seam between this server and Atlassian's APIs.

    Every product call goes through here, so token acquisition, cloud-id
    addressing and error translation live in one place instead of being
    repeated per service. Callers see only the exceptions in
    app.integration.linking.exceptions -- no raw vendor URLs, headers or
    response bodies escape to a REST client or an LLM tool caller.
    """

    def __init__(
        self,
        config: app_config.AppConfig,
        client: httpx2.AsyncClient,
        oauth: oauth_client.OAuthClient,
    ) -> None:
        self._config = config
        self._client = client
        self._oauth = oauth

    async def get(
        self,
        user_id: str,
        product: models.Product,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET a path relative to the product's cloud-addressed API root,
        e.g. ``/rest/api/3/search`` for Jira."""
        token = await self._oauth.get_valid_credentials(user_id)

        if token.cloud_id is None:
            msg = f"No Atlassian site resolved for user {user_id}"
            raise exceptions.AtlassianTokenError(msg)

        base = self._config.atlassian_config.api_base.rstrip("/")
        segment = _PRODUCT_PATH_SEGMENT[product]
        url = f"{base}/ex/{segment}/{token.cloud_id}{path}"

        return await self._request(url, token.access_token, params)

    async def get_me(self, user_id: str) -> Any:
        """GET the linked account's own profile. Not cloud-addressed -- /me
        hangs off the API root directly."""
        access_token = await self._oauth.get_valid_token(user_id)
        base = self._config.atlassian_config.api_base.rstrip("/")

        return await self._request(f"{base}/me", access_token, None)

    async def _request(
        self,
        url: str,
        access_token: str,
        params: dict[str, Any] | None,
    ) -> Any:
        try:
            response = await self._client.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
        except httpx2.RequestError as exc:
            raise exceptions.AtlassianUnavailableError(str(exc)) from exc

        try:
            response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            raise exceptions.AtlassianApiError(response.status_code) from exc

        return response.json()
