from collections.abc import Mapping
from typing import Any

import httpx2

from app.integration.atlassian import errors, models, ports


class AtlassianClient:
    """The single seam between this server and Atlassian's product APIs.

    Every product call goes through here, so addressing and error
    translation live in one place instead of being repeated per service.
    Where a call goes and how it is authorised come from the AtlassianAuth
    it is given, so the same client serves OAuth and API-token callers.
    Callers see only the exceptions in app.integration.atlassian.errors --
    no raw vendor URLs, headers or response bodies escape to a REST client
    or an LLM tool caller.
    """

    def __init__(self, http: httpx2.AsyncClient, auth: ports.AtlassianAuth) -> None:
        self._http = http
        self._auth = auth

    async def get(
        self,
        product: models.Product,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET a path relative to the product's API root, e.g.
        ``/rest/api/3/search/jql`` for Jira."""
        auth = await self._auth.authorize(product)
        return await get_json(
            self._http, f"{auth.base_url}{path}", auth.headers, params
        )


async def get_json(
    http: httpx2.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    params: dict[str, Any] | None = None,
) -> Any:
    """GET a URL and return the decoded JSON body, translating transport
    failures and non-2xx responses into the errors module's exceptions.

    Shared with callers outside the product services (the OAuth connection
    test) so the no-vendor-detail-escapes rule is enforced in one place.
    """
    try:
        response = await http.get(
            url,
            params=params,
            headers={**headers, "Accept": "application/json"},
        )
    except httpx2.RequestError as exc:
        raise errors.AtlassianUnavailableError(str(exc)) from exc

    try:
        response.raise_for_status()
    except httpx2.HTTPStatusError as exc:
        raise errors.AtlassianApiError(response.status_code) from exc

    return response.json()
