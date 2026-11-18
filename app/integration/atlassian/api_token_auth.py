"""AtlassianAuth for an Atlassian API token (the stdio entry point).

Both token kinds use HTTP basic auth with ``email:token``; they differ only
in where calls go:

- classic: the site itself, e.g. ``https://your-site.atlassian.net``. The
  services' paths already carry ``/rest/api/3`` (Jira) or ``/wiki``
  (Confluence), so the site URL is the base for both products.
- scoped: Atlassian's API gateway, ``https://api.atlassian.com/ex/{product}/
  {cloudId}`` -- the same addressing OAuth uses. Scoped tokens are rejected
  with a 401 on the site URL. The cloud id is looked up once at startup from
  ``{site_url}/_edge/tenant_info``, so users configure only the site URL.
"""

import base64
from collections.abc import Mapping
from typing import Any

import httpx2
import pydantic

from app.integration.atlassian import client as atlassian_client
from app.integration.atlassian import errors, models, ports

GATEWAY_BASE = "https://api.atlassian.com"


class CloudIdLookupError(Exception):
    """Raised when the site's cloud id cannot be read from
    ``/_edge/tenant_info`` (needed before any scoped-token call)."""


class ApiTokenAtlassianAuth:
    """Process-wide credentials: one user's API token, one site."""

    def __init__(
        self,
        base_urls: Mapping[models.Product, str],
        email: str,
        token: pydantic.SecretStr,
    ) -> None:
        self._base_urls = {p: url.rstrip("/") for p, url in base_urls.items()}
        credentials = f"{email}:{token.get_secret_value()}".encode()
        self._headers = {
            "Authorization": f"Basic {base64.b64encode(credentials).decode()}"
        }

    @classmethod
    def classic(
        cls, site_url: str, email: str, token: pydantic.SecretStr
    ) -> "ApiTokenAtlassianAuth":
        return cls(dict.fromkeys(models.Product, site_url), email, token)

    @classmethod
    def scoped(
        cls,
        cloud_id: str,
        email: str,
        token: pydantic.SecretStr,
        gateway_base: str = GATEWAY_BASE,
    ) -> "ApiTokenAtlassianAuth":
        gateway = gateway_base.rstrip("/")
        return cls(
            {
                product: f"{gateway}/ex/{product.value}/{cloud_id}"
                for product in models.Product
            },
            email,
            token,
        )

    async def authorize(self, product: models.Product) -> ports.RequestAuth:
        return ports.RequestAuth(
            base_url=self._base_urls[product], headers=self._headers
        )

    def __repr__(self) -> str:
        # Never render the Authorization header.
        return f"ApiTokenAtlassianAuth(base_urls={self._base_urls!r})"


async def resolve_cloud_id(http: httpx2.AsyncClient, site_url: str) -> str:
    """Read the site's cloud id from ``{site_url}/_edge/tenant_info``.

    The endpoint is unauthenticated and returns ``{"cloudId": "..."}``.
    Raises CloudIdLookupError, with a message for the user, on any failure.
    """
    url = f"{site_url.rstrip('/')}/_edge/tenant_info"
    try:
        payload: Any = await atlassian_client.get_json(http, url, {})
    except errors.AtlassianApiError as exc:
        msg = (
            f"Could not look up the cloud id for {site_url} "
            f"(HTTP {exc.status_code} from /_edge/tenant_info). "
            "Check ATLASSIAN_SITE_URL."
        )
        raise CloudIdLookupError(msg) from exc
    except errors.AtlassianUnavailableError as exc:
        msg = f"Could not reach {site_url} to look up its cloud id."
        raise CloudIdLookupError(msg) from exc

    cloud_id = payload.get("cloudId") if isinstance(payload, dict) else None
    if not isinstance(cloud_id, str) or not cloud_id:
        msg = f"{site_url}/_edge/tenant_info did not return a cloudId."
        raise CloudIdLookupError(msg)
    return cloud_id
