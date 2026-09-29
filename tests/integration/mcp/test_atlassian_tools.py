"""Behavioural tests for the MCP tool surface (app/infra/mcp/tools.py),
driven through mcp_client -- real transport auth, real dishka-built
Principal, real Jira/Confluence services. One happy path per tool asserting
real rendered content (not `isinstance(result, str)`), plus the error
envelopes as an MCP client actually sees them: `result.is_error` and the
message in `result.content[0].text`, not just an exception type on a direct
call.
"""

import datetime

import httpx2

from app.integration.atlassian import models
from tests.fixtures import atlassian as vendor
from tests.support import app as test_app

_ISSUE = vendor.issue(assignee="Dev User", description=vendor.adf_document())
_SEARCH = httpx2.Response(200, json=vendor.search_results(_ISSUE))
_NO_ISSUES = httpx2.Response(200, json=vendor.search_results())
_SPACES = httpx2.Response(200, json=vendor.space())


def _approved(space_key: str, *products: models.Product) -> models.SpaceAccessRequest:
    approvals = models.empty_products()
    for product in products:
        approvals[product] = models.ProductApproval(
            requested=True, status=models.ProductStatus.APPROVED
        )
    return models.SpaceAccessRequest(
        id=f"req-{space_key}",
        user_id="placeholder",
        space_key=space_key,
        reason="need it",
        iao="owner@defra.gov.uk",
        products=approvals,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )


class TestJira:
    async def test_search_renders_a_line_per_issue(self):
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok", responses=[_SEARCH]
        ) as (
            client,
            _overrides,
            _user_id,
        ):
            result = await client.call_tool(
                "search_jira_issues", {"project_key": "FARM"}
            )

        assert result.content[0].text == ("FARM-1 [Done] (Bug, Dev User) Fix the gate")

    async def test_search_with_no_match_says_so(self):
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok", responses=[_NO_ISSUES]
        ) as (client, _overrides, _user_id):
            result = await client.call_tool(
                "search_jira_issues", {"project_key": "FARM", "text": "nothing"}
            )

        assert result.content[0].text == "No issues matched in FARM."

    async def test_get_issue_renders_the_adf_description_as_text(self):
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok",
            responses=[httpx2.Response(200, json=_ISSUE)],
        ) as (client, _overrides, _user_id):
            result = await client.call_tool("get_jira_issue", {"issue_key": "FARM-1"})

        text = result.content[0].text
        assert "# FARM-1 Fix the gate" in text
        assert "Status: Done" in text
        assert "The gate is broken." in text

    async def test_a_key_that_is_not_an_issue_key_is_refused(self):
        """The project the guard checks comes from the key's own prefix, so a
        key with no prefix has to fail before the guard, not silently check
        an empty project."""
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok", responses=[]
        ) as (
            client,
            _overrides,
            _user_id,
        ):
            result = await client.call_tool(
                "get_jira_issue", {"issue_key": "nonsense"}, raise_on_error=False
            )

        assert result.is_error
        assert "not a Jira issue key" in result.content[0].text


class TestConfluence:
    async def test_list_pages_renders_id_and_title(self):
        pages = httpx2.Response(
            200, json=vendor.content_search({"id": "1", "title": "Onboarding"})
        )
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok", responses=[pages]
        ) as (
            client,
            _overrides,
            _user_id,
        ):
            result = await client.call_tool(
                "list_confluence_pages", {"space_key": "FARM"}
            )

        assert result.content[0].text == "1 Onboarding"

    async def test_get_page_renders_the_body(self):
        page = httpx2.Response(
            200, json=vendor.page(body=vendor.adf_document("Read this first."))
        )
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok", responses=[_SPACES, page]
        ) as (client, _overrides, _user_id):
            result = await client.call_tool(
                "get_confluence_page", {"space_key": "FARM", "page_id": "1"}
            )

        text = result.content[0].text
        assert "# Onboarding" in text
        assert "Read this first." in text

    async def test_a_page_from_another_space_is_refused(self):
        """The space key is what the guard checks, so a page that turns out
        to live somewhere else must not be returned just because the caller
        named a space they are allowed to read."""
        page = httpx2.Response(200, json=vendor.page(space_id="424242"))
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok", responses=[_SPACES, page]
        ) as (client, _overrides, _user_id):
            result = await client.call_tool(
                "get_confluence_page",
                {"space_key": "FARM", "page_id": "1"},
                raise_on_error=False,
            )

        assert result.is_error
        assert "not in FARM" in result.content[0].text


class TestErrorEnvelopes:
    async def test_calling_a_tool_unlinked_explains_how_to_connect(self):
        async with test_app.mcp_client(responses=[]) as (client, _overrides, _user_id):
            result = await client.call_tool(
                "search_jira_issues", {"project_key": "FARM"}, raise_on_error=False
            )

        assert result.is_error
        assert "connect your Atlassian account" in result.content[0].text

    async def test_an_api_failure_surfaces_the_status_code(self):
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok", responses=[httpx2.Response(500)]
        ) as (client, _overrides, _user_id):
            result = await client.call_tool(
                "search_jira_issues", {"project_key": "FARM"}, raise_on_error=False
            )

        assert result.is_error
        assert "500" in result.content[0].text

    async def test_an_unapproved_space_is_forbidden(self):
        """AllowListSpaceGuard denies when there is no approved request for
        this user and space -- an empty access-requests store already proves
        that, with no need for a bespoke always-deny fake."""
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok",
            responses=[],
            resource_guard_mode="allow_list",
        ) as (client, _overrides, _user_id):
            result = await client.call_tool(
                "search_jira_issues", {"project_key": "FARM"}, raise_on_error=False
            )

        assert result.is_error
        assert "No approved access request" in result.content[0].text

    async def test_approval_for_jira_does_not_open_confluence(self):
        """The whole point of per-product approval: the same space key is
        two separate decisions."""
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok",
            responses=[_SEARCH],
            resource_guard_mode="allow_list",
        ) as (client, overrides, user_id):
            request = _approved("FARM", models.Product.JIRA)
            request.user_id = user_id
            await overrides.access_requests.create(request)

            allowed = await client.call_tool(
                "search_jira_issues", {"project_key": "FARM"}, raise_on_error=False
            )
            denied = await client.call_tool(
                "list_confluence_pages", {"space_key": "FARM"}, raise_on_error=False
            )

        assert not allowed.is_error
        assert denied.is_error
        assert "confluence" in denied.content[0].text

    async def test_config_list_denies_a_key_not_on_the_jira_csv(self):
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok",
            responses=[],
            resource_guard_mode="config_list",
            resource_guard_allowed_jira_projects="OTHER",
            resource_guard_allowed_confluence_spaces="",
        ) as (client, _overrides, _user_id):
            result = await client.call_tool(
                "search_jira_issues", {"project_key": "FARM"}, raise_on_error=False
            )

        assert result.is_error
        assert "FARM" in result.content[0].text

    async def test_config_list_approval_for_jira_does_not_open_confluence(self):
        """Same per-product independence as allow_list, but from a
        hand-managed CSV rather than a Mongo-backed approval."""
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok",
            responses=[_SEARCH],
            resource_guard_mode="config_list",
            resource_guard_allowed_jira_projects="FARM",
            resource_guard_allowed_confluence_spaces="",
        ) as (client, _overrides, _user_id):
            allowed = await client.call_tool(
                "search_jira_issues", {"project_key": "FARM"}, raise_on_error=False
            )
            denied = await client.call_tool(
                "list_confluence_pages", {"space_key": "FARM"}, raise_on_error=False
            )

        assert not allowed.is_error
        assert denied.is_error
        assert "confluence" in denied.content[0].text


class TestListSpaces:
    async def test_reports_the_status_of_each_product(self):
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok", responses=[]
        ) as (
            client,
            overrides,
            user_id,
        ):
            request = _approved("FARM", models.Product.JIRA)
            request.user_id = user_id
            await overrides.access_requests.create(request)

            result = await client.call_tool("list_spaces", {})

        assert result.content[0].text == (
            "FARM (jira: approved, confluence: not-requested)"
        )

    async def test_says_so_when_nothing_has_been_requested(self):
        async with test_app.mcp_client(
            atlassian_token="atlassian-tok", responses=[]
        ) as (
            client,
            _overrides,
            _user_id,
        ):
            result = await client.call_tool("list_spaces", {})

        assert "No spaces requested" in result.content[0].text
