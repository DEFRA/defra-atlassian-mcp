from collections.abc import AsyncIterator

import dishka
import httpx2

from app import config as app_config
from app.common import http_client, request_context
from app.integration.atlassian import client as atlassian_client
from app.integration.atlassian import connection_test_service
from app.integration.atlassian import guard as guard_module
from app.integration.atlassian.confluence import service as confluence_service
from app.integration.atlassian.jira import service as jira_service
from app.integration.linking import oauth_client
from app.integration.linking import ports as token_store
from app.integration.linking import service as linking_service


class RequestScopeProvider(dishka.Provider):
    """REQUEST-scoped wiring: per-request httpx2 client plus the services that
    use it (OAuthClient, AtlassianClient, the product services).
    RequestContext arrives via from_context — populated by the FastAPI
    middleware (HTTP) or the dishka_inject decorator (MCP)."""

    scope = dishka.Scope.REQUEST

    rc = dishka.from_context(request_context.RequestContext)

    @dishka.provide
    async def provide_httpx_client(
        self,
        config: app_config.AppConfig,
        rc: request_context.RequestContext,
    ) -> AsyncIterator[httpx2.AsyncClient]:
        proxy = str(config.http_proxy) if config.http_proxy else None
        async with http_client.create_async_client(
            tracing_header=config.tracing_header,
            trace_id=rc.trace_id,
            proxy=proxy,
        ) as client:
            yield client

    @dishka.provide
    def provide_oauth_client(
        self,
        config: app_config.AppConfig,
        client: httpx2.AsyncClient,
        tokens: token_store.TokenStore,
    ) -> oauth_client.OAuthClient:
        return oauth_client.OAuthClient(config=config, client=client, tokens=tokens)

    @dishka.provide
    def provide_linking_service(
        self,
        oauth: oauth_client.OAuthClient,
        tokens: token_store.TokenStore,
        states: token_store.OAuthStateStore,
    ) -> linking_service.LinkingService:
        return linking_service.LinkingService(oauth=oauth, tokens=tokens, states=states)

    @dishka.provide
    def provide_atlassian_client(
        self,
        config: app_config.AppConfig,
        client: httpx2.AsyncClient,
        oauth: oauth_client.OAuthClient,
    ) -> atlassian_client.AtlassianClient:
        return atlassian_client.AtlassianClient(
            config=config,
            client=client,
            oauth=oauth,
        )

    @dishka.provide
    def provide_connection_test_service(
        self,
        client: atlassian_client.AtlassianClient,
    ) -> connection_test_service.AtlassianConnectionTestService:
        return connection_test_service.AtlassianConnectionTestService(client=client)

    @dishka.provide
    def provide_jira_service(
        self,
        client: atlassian_client.AtlassianClient,
        guard: guard_module.SpaceGuard,
    ) -> jira_service.JiraService:
        return jira_service.JiraService(client=client, guard=guard)

    @dishka.provide
    def provide_confluence_service(
        self,
        client: atlassian_client.AtlassianClient,
        guard: guard_module.SpaceGuard,
    ) -> confluence_service.ConfluenceService:
        return confluence_service.ConfluenceService(client=client, guard=guard)
