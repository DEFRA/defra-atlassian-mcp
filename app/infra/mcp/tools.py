import functools
from collections.abc import Awaitable, Callable
from typing import Any

import dishka
import fastmcp
from fastmcp import exceptions as fastmcp_exceptions

from app.auth import principal as principal_module
from app.infra.mcp import dishka_inject
from app.integration.atlassian import access_request_service as approvals_module
from app.integration.atlassian import guard as guard_module
from app.integration.atlassian import models as approval_models
from app.integration.atlassian.confluence import service as confluence_module
from app.integration.atlassian.jira import service as jira_module
from app.integration.linking import exceptions

_NOT_LINKED_MESSAGE = (
    "No Atlassian credentials found. Please connect your Atlassian account "
    "in the portal first."
)
_NO_SITE_MESSAGE = "The linked Atlassian account has access to no sites."
_UNAVAILABLE_MESSAGE = "Atlassian is unreachable. Please try again later."

# Domain exceptions whose own message is already written for the caller.
_PASS_THROUGH_ERRORS = (
    guard_module.ForbiddenSpaceError,
    jira_module.IssueNotFoundError,
    confluence_module.SpaceNotFoundError,
    confluence_module.PageNotFoundError,
)


def _translate_errors(
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
        except exceptions.AtlassianTokenError as err:
            raise fastmcp_exceptions.ToolError(_NOT_LINKED_MESSAGE) from err
        except exceptions.NoAccessibleSiteError as err:
            raise fastmcp_exceptions.ToolError(_NO_SITE_MESSAGE) from err
        except exceptions.AtlassianUnavailableError as err:
            raise fastmcp_exceptions.ToolError(_UNAVAILABLE_MESSAGE) from err
        except exceptions.AtlassianApiError as err:
            message = f"Atlassian API request failed with status {err.status_code}."
            raise fastmcp_exceptions.ToolError(message) from err
        except _PASS_THROUGH_ERRORS as err:
            raise fastmcp_exceptions.ToolError(str(err)) from err

    return wrapper


@dishka_inject.inject
@_translate_errors
async def list_spaces(
    _ctx: fastmcp.Context,
    approvals: dishka.FromDishka[approvals_module.SpaceAccessRequestService],
    principal: dishka.FromDishka[principal_module.Principal],
) -> str:
    """List the Atlassian spaces and project keys you have requested, with the approval status of each for Jira and Confluence."""
    requests = await approvals.list_for_user(principal.user_id)

    if not requests:
        return (
            "No spaces requested. Request access to a space in the portal "
            "before using the Jira or Confluence tools."
        )

    lines = []
    for request in sorted(requests, key=lambda r: r.space_key):
        statuses = ", ".join(
            f"{product.value}: {request.product(product).status.value}"
            for product in approval_models.Product
        )
        lines.append(f"{request.space_key} ({statuses})")

    return "\n".join(lines)


@dishka_inject.inject
@_translate_errors
async def search_jira_issues(
    project_key: str,
    _ctx: fastmcp.Context,
    jira: dishka.FromDishka[jira_module.JiraService],
    principal: dishka.FromDishka[principal_module.Principal],
    text: str | None = None,
    status: str | None = None,
    limit: int = 25,
) -> str:
    """Search issues in a Jira project, most recently updated first. Optionally filter by free text and/or status name."""
    return await jira.search_issues(
        principal.user_id,
        project_key,
        text=text,
        status=status,
        limit=limit,
    )


@dishka_inject.inject
@_translate_errors
async def get_jira_issue(
    issue_key: str,
    _ctx: fastmcp.Context,
    jira: dishka.FromDishka[jira_module.JiraService],
    principal: dishka.FromDishka[principal_module.Principal],
) -> str:
    """Return one Jira issue's fields and description, given its key (e.g. FARM-123)."""
    return await jira.get_issue(principal.user_id, issue_key)


@dishka_inject.inject
@_translate_errors
async def list_confluence_pages(
    space_key: str,
    _ctx: fastmcp.Context,
    confluence: dishka.FromDishka[confluence_module.ConfluenceService],
    principal: dishka.FromDishka[principal_module.Principal],
    query: str | None = None,
    limit: int = 25,
) -> str:
    """List pages in a Confluence space, most recently modified first. Optionally filter by free text."""
    return await confluence.list_pages(
        principal.user_id,
        space_key,
        query=query,
        limit=limit,
    )


@dishka_inject.inject
@_translate_errors
async def get_confluence_page(
    space_key: str,
    page_id: str,
    _ctx: fastmcp.Context,
    confluence: dishka.FromDishka[confluence_module.ConfluenceService],
    principal: dishka.FromDishka[principal_module.Principal],
) -> str:
    """Return one Confluence page's content as text. The space key is required so access can be checked before the page is fetched."""
    return await confluence.get_page(principal.user_id, space_key, page_id)


def register_tools(mcp_app: fastmcp.FastMCP) -> None:
    mcp_app.tool()(list_spaces)
    mcp_app.tool()(search_jira_issues)
    mcp_app.tool()(get_jira_issue)
    mcp_app.tool()(list_confluence_pages)
    mcp_app.tool()(get_confluence_page)
