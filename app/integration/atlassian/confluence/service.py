import json
from typing import Any

from app.integration.atlassian import client as atlassian_client
from app.integration.atlassian import guard as guard_module
from app.integration.atlassian import models
from app.integration.atlassian.content import adf

_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100


class SpaceNotFoundError(Exception):
    """Raised when a space key does not resolve to a Confluence space."""


class PageNotFoundError(Exception):
    """Raised when a page id does not resolve to a page in the given
    space."""


class ConfluenceService:
    """Read-only Confluence access, gated per space key.

    Every public method calls the guard first, before a token is fetched or
    any vendor call is made.
    """

    def __init__(
        self,
        client: atlassian_client.AtlassianClient,
        guard: guard_module.SpaceGuard,
    ) -> None:
        self._client = client
        self._guard = guard

    async def list_pages(
        self,
        user_id: str,
        space_key: str,
        query: str | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> str:
        await self._guard.check(user_id, space_key, models.Product.CONFLUENCE)

        cql = f"space = {_quote(space_key)} AND type = page"
        if query:
            cql += f" AND text ~ {_quote(query)}"
        cql += " ORDER BY lastmodified DESC"

        payload = await self._client.get(
            user_id,
            models.Product.CONFLUENCE,
            "/wiki/rest/api/content/search",
            params={"cql": cql, "limit": _clamp(limit)},
        )

        results = payload.get("results", [])
        if not results:
            return f"No pages matched in {space_key}."

        return "\n".join(
            f"{result.get('id', '')} {result.get('title', '')}" for result in results
        )

    async def get_page(self, user_id: str, space_key: str, page_id: str) -> str:
        """Fetch one page's content.

        The space is passed explicitly so the guard can run before any vendor
        call, but the page is then checked to actually live in that space --
        otherwise naming a space you are approved for would read a page from
        one you are not.
        """
        await self._guard.check(user_id, space_key, models.Product.CONFLUENCE)

        space_id = await self._resolve_space_id(user_id, space_key)

        page = await self._client.get(
            user_id,
            models.Product.CONFLUENCE,
            f"/wiki/api/v2/pages/{page_id}",
            params={"body-format": "atlas_doc_format"},
        )

        if str(page.get("spaceId")) != space_id:
            msg = f"Page {page_id} is not in {space_key}."
            raise PageNotFoundError(msg)

        return _render_page(page)

    async def _resolve_space_id(self, user_id: str, space_key: str) -> str:
        payload = await self._client.get(
            user_id,
            models.Product.CONFLUENCE,
            "/wiki/api/v2/spaces",
            params={"keys": space_key, "limit": 1},
        )

        results = payload.get("results", [])
        if not results:
            msg = f"No Confluence space with key {space_key}."
            raise SpaceNotFoundError(msg)

        return str(results[0]["id"])


def _clamp(limit: int) -> int:
    return max(1, min(limit, _MAX_LIMIT))


def _quote(value: str) -> str:
    """Quote a CQL string literal, escaping the backslash before the quote so
    a crafted value cannot close the literal and append its own clause."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_page(page: dict[str, Any]) -> str:
    lines = [f"# {page.get('title', '')}", f"Id: {page.get('id', '')}"]

    body = page.get("body", {}).get("atlas_doc_format", {}).get("value")
    rendered = adf.render(_as_document(body))
    if rendered:
        lines.extend(["", rendered])

    return "\n".join(lines)


def _as_document(body: Any) -> Any:
    """Confluence returns the ADF document as a JSON *string*, unlike Jira
    which returns it as a nested object."""
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None
    return body
