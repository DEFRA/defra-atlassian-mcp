"""The MCP tools shared by both entry points.

Nothing here may import HTTP-only code (the approvals workflow, OAuth
linking, Principal): the stdio entry point registers these same functions.
HTTP-only tools live in app.infra.mcp.http_tools.
"""

import functools
from collections.abc import Awaitable, Callable
from typing import Any

import dishka
import fastmcp
from fastmcp import exceptions as fastmcp_exceptions

from app.infra.mcp import dishka_inject
from app.integration.atlassian import errors, models
from app.integration.atlassian import guard as guard_module
from app.integration.atlassian.confluence import service as confluence_module
from app.integration.atlassian.jira import service as jira_module

_UNAVAILABLE_MESSAGE = "Atlassian is unreachable. Please try again later."

# Domain exceptions whose own message is already written for the caller.
# AtlassianCredentialsError is among them: each AtlassianAuth knows what the
# caller can do about missing credentials (link an account in the portal,
# or fix the API token in the stdio settings), so it writes the message.
_PASS_THROUGH_ERRORS = (
    errors.AtlassianCredentialsError,
    guard_module.ForbiddenResourceError,
    jira_module.IssueNotFoundError,
    confluence_module.SpaceNotFoundError,
    confluence_module.PageNotFoundError,
)


def translate_errors(
    func: Callable[..., Awaitable[str]],
) -> Callable[..., Awaitable[str]]:
    """Turn domain exceptions into the ToolError envelope an MCP client sees.

    Every tool needs the same ladder, so it lives here once rather than being
    repeated per tool. Vendor status codes are surfaced but vendor URLs,
    headers and bodies are not.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return await func(*args, **kwargs)
        except errors.AtlassianUnavailableError as err:
            raise fastmcp_exceptions.ToolError(_UNAVAILABLE_MESSAGE) from err
        except errors.AtlassianApiError as err:
            message = f"Atlassian API request failed with status {err.status_code}."
            raise fastmcp_exceptions.ToolError(message) from err
        except _PASS_THROUGH_ERRORS as err:
            raise fastmcp_exceptions.ToolError(str(err)) from err

    return wrapper


@dishka_inject.inject
@translate_errors
async def search_jira_issues(
    project_key: str,
    _ctx: fastmcp.Context,
    jira: dishka.FromDishka[jira_module.JiraService],
    text: str | None = None,
    status: str | None = None,
    limit: int = 25,
) -> str:
    """Search issues in a Jira project, most recently updated first. Optionally filter by free text and/or status name."""
    return await jira.search_issues(
        project_key,
        text=text,
        status=status,
        limit=limit,
    )


@dishka_inject.inject
@translate_errors
async def get_jira_issue(
    issue_key: str,
    _ctx: fastmcp.Context,
    jira: dishka.FromDishka[jira_module.JiraService],
) -> str:
    """Return one Jira issue's fields and description, given its key (e.g. FARM-123)."""
    return await jira.get_issue(issue_key)


@dishka_inject.inject
@translate_errors
async def list_confluence_pages(
    space_key: str,
    _ctx: fastmcp.Context,
    confluence: dishka.FromDishka[confluence_module.ConfluenceService],
    query: str | None = None,
    limit: int = 25,
) -> str:
    """List pages in a Confluence space, most recently modified first. Optionally filter by free text."""
    return await confluence.list_pages(
        space_key,
        query=query,
        limit=limit,
    )


@dishka_inject.inject
@translate_errors
async def get_confluence_page(
    space_key: str,
    page_id: str,
    _ctx: fastmcp.Context,
    confluence: dishka.FromDishka[confluence_module.ConfluenceService],
) -> str:
    """Return one Confluence page's content as text. The space key is required so access can be checked before the page is fetched."""
    return await confluence.get_page(space_key, page_id)


@dishka_inject.inject
@translate_errors
async def list_allowed_keys(
    _ctx: fastmcp.Context,
    allowlist: dishka.FromDishka[guard_module.StaticAllowlistSource],
) -> str:
    """List the Jira project keys and Confluence space keys this server is allowed to read. Use these keys with the other tools."""
    lines = []
    for product, label in (
        (models.Product.JIRA, "Jira projects"),
        (models.Product.CONFLUENCE, "Confluence spaces"),
    ):
        keys = sorted(allowlist.keys_for(product))
        lines.append(f"{label}: {', '.join(keys) if keys else '(none)'}")
    return "\n".join(lines)


def register_core_tools(mcp_app: fastmcp.FastMCP) -> None:
    """The four Jira/Confluence tools, available on every entry point."""
    mcp_app.tool()(search_jira_issues)
    mcp_app.tool()(get_jira_issue)
    mcp_app.tool()(list_confluence_pages)
    mcp_app.tool()(get_confluence_page)


def register_allowlist_tool(mcp_app: fastmcp.FastMCP) -> None:
    """list_allowed_keys reports the static allowlist, so it is registered
    only where that list is what is enforced: always on stdio, and on HTTP
    in RESOURCE_GUARD_MODE=config_list."""
    mcp_app.tool()(list_allowed_keys)
