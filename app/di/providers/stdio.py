"""Dishka wiring for the stdio entry point.

Everything is APP-scoped: there is one user, one token and one allowlist
for the life of the process. The MCP tools still open a REQUEST scope per
call (app.infra.mcp.dishka_inject); APP-scoped objects resolve from it.

Must not import HTTP-only modules -- see tests/unit/test_stdio_layering.py.
"""

from collections.abc import AsyncIterator

import dishka
import httpx2

from app.common import http_client
from app.config import stdio as stdio_config
from app.integration.atlassian import api_token_auth, guard, ports
from app.integration.atlassian import client as atlassian_client
from app.integration.atlassian.confluence import service as confluence_service
from app.integration.atlassian.jira import service as jira_service


class StdioProvider(dishka.Provider):
    scope = dishka.Scope.APP

    settings = dishka.from_context(stdio_config.StdioSettings)

    @dishka.provide
    async def provide_http_client(
        self, settings: stdio_config.StdioSettings
    ) -> AsyncIterator[httpx2.AsyncClient]:
        proxy = str(settings.http_proxy) if settings.http_proxy else None
        async with http_client.create_async_client(
            proxy=proxy, request_timeout=settings.request_timeout_seconds
        ) as client:
            yield client

    @dishka.provide
    async def provide_atlassian_auth(
        self,
        settings: stdio_config.StdioSettings,
        http: httpx2.AsyncClient,
    ) -> ports.AtlassianAuth:
        """For a scoped token this looks up the cloud id, so resolving it
        makes a network call; the entry point resolves it once at startup."""
        site_url = str(settings.site_url)
        if settings.api_token_type == "scoped":  # noqa: S105 -- a token kind, not a secret
            cloud_id = await api_token_auth.resolve_cloud_id(http, site_url)
            return api_token_auth.ApiTokenAtlassianAuth.scoped(
                cloud_id, settings.email, settings.api_token
            )
        return api_token_auth.ApiTokenAtlassianAuth.classic(
            site_url, settings.email, settings.api_token
        )

    @dishka.provide
    def provide_atlassian_client(
        self, http: httpx2.AsyncClient, auth: ports.AtlassianAuth
    ) -> atlassian_client.AtlassianClient:
        return atlassian_client.AtlassianClient(http=http, auth=auth)

    @dishka.provide
    def provide_static_allowlist(
        self, settings: stdio_config.StdioSettings
    ) -> guard.StaticAllowlistSource:
        return guard.StaticAllowlistSource(
            settings.resource_guard_allowed_jira_projects,
            settings.resource_guard_allowed_confluence_spaces,
        )

    @dishka.provide
    def provide_access_policy(
        self, source: guard.StaticAllowlistSource
    ) -> guard.AccessPolicy:
        return guard.AllowlistAccessPolicy(source)

    @dishka.provide
    def provide_jira_service(
        self,
        client: atlassian_client.AtlassianClient,
        policy: guard.AccessPolicy,
    ) -> jira_service.JiraService:
        return jira_service.JiraService(client=client, policy=policy)

    @dishka.provide
    def provide_confluence_service(
        self,
        client: atlassian_client.AtlassianClient,
        policy: guard.AccessPolicy,
    ) -> confluence_service.ConfluenceService:
        return confluence_service.ConfluenceService(client=client, policy=policy)
