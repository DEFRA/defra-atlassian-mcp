"""MCP tools that exist only on the HTTP entry point, because they depend
on the portal's access-request workflow and on a per-user Principal."""

import dishka
import fastmcp

from app.auth import principal as principal_module
from app.infra.mcp import dishka_inject
from app.infra.mcp.tools import translate_errors
from app.integration.atlassian import access_request_service as approvals_module
from app.integration.atlassian import models as approval_models


@dishka_inject.inject
@translate_errors
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


def register_http_tools(mcp_app: fastmcp.FastMCP) -> None:
    mcp_app.tool()(list_spaces)
