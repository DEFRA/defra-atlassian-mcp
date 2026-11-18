"""The stdio server end to end, minus the process boundary: the real stdio
container, server and tools, driven through the in-memory fastmcp.Client.
Only the outbound HTTP client is faked. (No transport auth exists on stdio,
so unlike the HTTP tests the in-memory transport can call tools.)"""

import base64
import contextlib

import dishka
import fastmcp
import httpx2
import pydantic

from app.config import stdio as stdio_config
from app.di import stdio_container
from app.entrypoints import stdio as entrypoint
from tests.fakes import httpx_helpers
from tests.fixtures import atlassian as vendor

_BASIC = "Basic " + base64.b64encode(b"dev@example.com:s3cret").decode()


def _settings(**overrides) -> stdio_config.StdioSettings:
    values = {
        "site_url": "https://example.atlassian.net",
        "email": "dev@example.com",
        "api_token": pydantic.SecretStr("s3cret"),
        "api_token_type": "classic",
        "skip_startup_check": True,
        "log_level": "INFO",
        "request_timeout_seconds": 30,
        "http_proxy": None,
        "resource_guard_allowed_jira_projects": frozenset({"FARM"}),
        "resource_guard_allowed_confluence_spaces": frozenset({"ENG"}),
        **overrides,
    }
    values["site_url"] = pydantic.HttpUrl(values["site_url"])
    return stdio_config.StdioSettings.model_construct(**values)


class _FakeHttp(dishka.Provider):
    def __init__(self, transport: httpx_helpers.MockTransport) -> None:
        super().__init__()
        self._transport = transport

    @dishka.provide(scope=dishka.Scope.APP, override=True)
    def provide_http_client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=self._transport)


@contextlib.asynccontextmanager
async def _server(responses, **settings_overrides):
    settings = _settings(**settings_overrides)
    transport = httpx_helpers.MockTransport(responses)
    container = stdio_container.build_stdio_container(settings, _FakeHttp(transport))
    async with container:
        await entrypoint.prepare(container, settings)
        async with fastmcp.Client(entrypoint.build(container)) as client:
            yield client, transport


class TestToolSet:
    async def test_exposes_the_core_tools_and_the_allowlist_tool(self):
        async with _server([]) as (client, _):
            tools = {t.name for t in await client.list_tools()}

        assert tools == {
            "search_jira_issues",
            "get_jira_issue",
            "list_confluence_pages",
            "get_confluence_page",
            "list_allowed_keys",
        }


class TestClassicToken:
    async def test_calls_the_site_with_basic_auth(self):
        search = httpx2.Response(200, json=vendor.search_results(vendor.issue()))
        async with _server([search]) as (client, transport):
            result = await client.call_tool(
                "search_jira_issues", {"project_key": "FARM"}
            )

        assert result.content[0].text == "FARM-1 [Done] (Bug, Unassigned) Fix the gate"
        request = transport.requests[0]
        assert str(request.url).startswith(
            "https://example.atlassian.net/rest/api/3/search/jql"
        )
        assert request.headers["Authorization"] == _BASIC

    async def test_confluence_paths_keep_their_wiki_prefix(self):
        pages = httpx2.Response(
            200, json=vendor.content_search({"id": "1", "title": "Intro"})
        )
        async with _server([pages]) as (client, transport):
            await client.call_tool("list_confluence_pages", {"space_key": "ENG"})

        assert str(transport.requests[0].url).startswith(
            "https://example.atlassian.net/wiki/rest/api/content/search"
        )


class TestScopedToken:
    async def test_looks_up_the_cloud_id_once_then_uses_the_gateway(self):
        tenant = httpx2.Response(200, json={"cloudId": "cloud-1"})
        search = httpx2.Response(200, json=vendor.search_results())
        async with _server([tenant, search], api_token_type="scoped") as (
            client,
            transport,
        ):
            await client.call_tool("search_jira_issues", {"project_key": "FARM"})
            await client.list_tools()

        urls = [str(r.url) for r in transport.requests]
        assert urls[0] == "https://example.atlassian.net/_edge/tenant_info"
        assert urls[1].startswith(
            "https://api.atlassian.com/ex/jira/cloud-1/rest/api/3/search/jql"
        )
        assert len(urls) == 2
        assert transport.requests[1].headers["Authorization"] == _BASIC


class TestAllowlist:
    async def test_a_key_outside_the_allowlist_is_refused_without_a_call(self):
        async with _server([]) as (client, transport):
            result = await client.call_tool(
                "search_jira_issues", {"project_key": "OTHER"}, raise_on_error=False
            )

        assert result.is_error
        assert "OTHER" in result.content[0].text
        assert transport.requests == []

    async def test_a_path_traversal_key_is_refused(self):
        async with _server([]) as (client, transport):
            result = await client.call_tool(
                "get_jira_issue",
                {"issue_key": "FARM-1/../OTHER-5"},
                raise_on_error=False,
            )

        assert result.is_error
        assert transport.requests == []

    async def test_list_allowed_keys_reports_the_configured_lists(self):
        async with _server([]) as (client, _):
            result = await client.call_tool("list_allowed_keys", {})

        assert result.content[0].text == "Jira projects: FARM\nConfluence spaces: ENG"


class TestErrors:
    async def test_a_rejected_token_surfaces_the_status_not_a_portal_hint(self):
        async with _server([httpx2.Response(401)]) as (client, _):
            result = await client.call_tool(
                "search_jira_issues", {"project_key": "FARM"}, raise_on_error=False
            )

        assert result.is_error
        assert "401" in result.content[0].text
        assert "portal" not in result.content[0].text
