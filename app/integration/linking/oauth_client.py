import datetime
import urllib.parse
from typing import Any

import httpx2

from app import config as app_config
from app.integration.linking import exceptions, models, ports

_LEEWAY = datetime.timedelta(seconds=60)

_AUTHORIZE_PATH = "/authorize"
_TOKEN_PATH = "/oauth/token"  # noqa: S105
_AUDIENCE = "api.atlassian.com"
_SCOPES = (
    "read:jira-work read:jira-user read:confluence-space.summary "
    "read:confluence-content.summary offline_access"
)


class OAuthClient:
    """Handles Atlassian's OAuth 2.0 (3LO) code-exchange and refresh flows.

    Access tokens are treated as opaque bearer strings and never decoded or
    signature-checked here. Trust comes from how the token was obtained --
    TLS to ``atlassian_config.auth_base`` plus ``client_secret``
    authentication at the token endpoint -- and Atlassian's API is the only
    authority on a token's continued validity, surfaced as a 401 on the next
    real call (see ``exceptions.AtlassianApiError``). Expiry is read from the
    token response's ``expires_in`` field, not from the token itself.

    Two things differ from a textbook OAuth client, both required by
    Atlassian: the token endpoint takes a JSON body rather than form encoding,
    and the site the token addresses ("cloud id") is not in the token response
    at all -- it comes from a follow-up call to
    ``/oauth/token/accessible-resources``.
    """

    def __init__(
        self,
        config: app_config.AppConfig,
        client: httpx2.AsyncClient,
        tokens: ports.TokenStore,
    ) -> None:
        self._config = config
        self._client = client
        self._tokens = tokens

    @property
    def redirect_uri(self) -> str:
        return self._config.atlassian_config.redirect_uri

    @property
    def _token_url(self) -> str:
        base = self._config.atlassian_config.auth_base.rstrip("/")
        return base + _TOKEN_PATH

    def build_authorization_url(self, state: str, code_challenge: str) -> str:
        atlassian_config = self._config.atlassian_config
        base = atlassian_config.auth_base.rstrip("/")
        auth_url = base + _AUTHORIZE_PATH
        params = urllib.parse.urlencode(
            {
                "audience": _AUDIENCE,
                "client_id": atlassian_config.client_id,
                "scope": _SCOPES,
                "redirect_uri": self.redirect_uri,
                "state": state,
                "response_type": "code",
                # Atlassian will not issue a refresh token for the
                # offline_access scope without an explicit consent prompt.
                "prompt": "consent",
                # PKCE (RFC 7636), on top of client_secret auth at the token
                # endpoint -- defense in depth, not a replacement for it.
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{auth_url}?{params}"

    def _to_token(
        self,
        data: dict[str, Any],
        fallback_refresh_token: str,
        cloud_id: str | None = None,
    ) -> models.AtlassianToken:
        expires_in = data.get("expires_in")
        expires_at = (
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=expires_in)
            if expires_in is not None
            else None
        )
        return models.AtlassianToken(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", fallback_refresh_token),
            expires_at=expires_at,
            cloud_id=cloud_id,
        )

    async def _post_token(self, payload: dict[str, Any]) -> dict[str, Any]:
        atlassian_config = self._config.atlassian_config

        try:
            response = await self._client.post(
                self._token_url,
                json={
                    **payload,
                    "client_id": atlassian_config.client_id,
                    "client_secret": atlassian_config.client_secret.get_secret_value(),
                },
            )
        except httpx2.RequestError as exc:
            raise exceptions.AtlassianUnavailableError(str(exc)) from exc

        try:
            response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            raise exceptions.AtlassianApiError(response.status_code) from exc

        data: dict[str, Any] = response.json()
        return data

    async def fetch_cloud_id(self, access_token: str) -> str:
        """Resolve the Atlassian site this token addresses.

        Raises exceptions.NoAccessibleSiteError when the granted account can
        reach no site, since without a cloud id no product API call can be
        built.
        """
        base = self._config.atlassian_config.api_base.rstrip("/")

        try:
            response = await self._client.get(
                f"{base}/oauth/token/accessible-resources",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx2.RequestError as exc:
            raise exceptions.AtlassianUnavailableError(str(exc)) from exc

        try:
            response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            raise exceptions.AtlassianApiError(response.status_code) from exc

        sites = response.json()

        if not sites:
            msg = "The linked Atlassian account has access to no sites."
            raise exceptions.NoAccessibleSiteError(msg)

        cloud_id: str = sites[0]["id"]
        return cloud_id

    async def exchange_code(
        self, code: str, code_verifier: str
    ) -> models.AtlassianToken:
        data = await self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        cloud_id = await self.fetch_cloud_id(data["access_token"])
        return self._to_token(data, fallback_refresh_token="", cloud_id=cloud_id)

    async def refresh(
        self, refresh_token_value: str, cloud_id: str | None = None
    ) -> models.AtlassianToken:
        data = await self._post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token_value,
            }
        )
        return self._to_token(
            data,
            fallback_refresh_token=refresh_token_value,
            cloud_id=cloud_id,
        )

    async def get_valid_credentials(self, user_id: str) -> models.AtlassianToken:
        """Return the user's stored token, refreshing it first if it is at or
        near expiry. Raises exceptions.AtlassianTokenError if the user has
        never linked an account."""
        token = await self._tokens.get_tokens(user_id)

        if token is None:
            msg = f"No Atlassian token for user {user_id}"
            raise exceptions.AtlassianTokenError(msg)

        is_expired = (
            token.expires_at is not None
            and token.expires_at <= datetime.datetime.now(datetime.UTC) + _LEEWAY
        )
        if is_expired:
            token = await self.refresh(token.refresh_token, cloud_id=token.cloud_id)
            await self._tokens.store_tokens(user_id, token)

        return token

    async def get_valid_token(self, user_id: str) -> str:
        token = await self.get_valid_credentials(user_id)
        return token.access_token
