"""Registration and schema tests for the MCP tool surface
(app/infra/mcp/tools.py), driven through the in-memory fastmcp.Client
(FastMCPTransport) -- cheap, and the generated schema is a contract this
repo did not write by hand.
"""

import pytest

from tests.support import app as test_app

_EXPECTED_SCHEMAS = {
    "list_spaces": set(),
    "search_jira_issues": {"project_key", "text", "status", "limit"},
    "get_jira_issue": {"issue_key"},
    "list_confluence_pages": {"space_key", "query", "limit"},
    "get_confluence_page": {"space_key", "page_id"},
}

_EXPECTED_REQUIRED = {
    "list_spaces": set(),
    "search_jira_issues": {"project_key"},
    "get_jira_issue": {"issue_key"},
    "list_confluence_pages": {"space_key"},
    "get_confluence_page": {"space_key", "page_id"},
}


class TestRegistration:
    async def test_exposes_exactly_the_atlassian_tools(self):
        async with test_app.mcp_registry_client() as client:
            tools = await client.list_tools()

            assert {t.name for t in tools} == set(_EXPECTED_SCHEMAS)


class TestToolSchema:
    @pytest.mark.parametrize("tool_name", sorted(_EXPECTED_SCHEMAS))
    async def test_exposes_only_its_public_parameters(self, tool_name):
        """No server-side parameter -- the fastmcp.Context each tool takes
        as `_ctx`, or a FromDishka-injected dependency -- leaks into the
        schema an LLM sees. If it did, a model would be asked to invent a
        value for it. The error-translation decorator wrapping every tool
        must preserve the signature for the same reason.
        """
        async with test_app.mcp_registry_client() as client:
            tools = {t.name: t for t in await client.list_tools()}

            properties = set(tools[tool_name].inputSchema.get("properties") or {})

            assert properties == _EXPECTED_SCHEMAS[tool_name]

    @pytest.mark.parametrize("tool_name", sorted(_EXPECTED_SCHEMAS))
    async def test_marks_the_right_parameters_required(self, tool_name):
        async with test_app.mcp_registry_client() as client:
            tools = {t.name: t for t in await client.list_tools()}

            required = set(tools[tool_name].inputSchema.get("required") or [])

            assert required == _EXPECTED_REQUIRED[tool_name]

    @pytest.mark.parametrize("tool_name", sorted(_EXPECTED_SCHEMAS))
    async def test_description_is_non_empty(self, tool_name):
        """Descriptions come from docstrings and are the primary thing an
        LLM uses to choose a tool -- an empty one is silently unusable."""
        async with test_app.mcp_registry_client() as client:
            tools = {t.name: t for t in await client.list_tools()}

            assert tools[tool_name].description
            assert tools[tool_name].description.strip() != ""
