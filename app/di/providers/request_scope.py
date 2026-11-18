from collections.abc import AsyncIterator

import dishka
import httpx2

from app import config as app_config
from app.auth import principal as principal_module
from app.common import http_client, request_context
from app.integration.atlassian import approved_requests_source, connection_test_service
from app.integration.atlassian import client as atlassian_client
from app.integration.atlassian import guard as guard_module
from app.integration.atlassian import ports as atlassian_ports
from app.integration.atlassian.confluence import service as confluence_service
from app.integration.atlassian.jira import service as jira_service
from app.integration.linking import oauth_auth, oauth_client
from app.integration.linking import ports as token_store
from app.integration.linking import service as linking_service


class RequestScopeProvider(dishka.Provider):
    """REQUEST-scoped wiring: per-request httpx2 client plus the services that
    use it (OAuthClient, the user-bound AtlassianAuth, AtlassianClient, the
    product services).
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
    def provide_atlassian_auth(
        self,
        config: app_config.AppConfig,
        oauth: oauth_client.OAuthClient,
        principal: principal_module.Principal,
    ) -> atlassian_ports.AtlassianAuth:
        """Binds the calling user's OAuth credentials for this request, so
        the client and services never see a user id. Principal is only
        resolvable inside an MCP tool call, which is the only place the
        product services are used."""
        return oauth_auth.OAuthAtlassianAuth(
            user_id=principal.user_id,
            oauth=oauth,
            api_base=config.atlassian_config.api_base,
        )

    @dishka.provide
    def provide_atlassian_client(
        self,
        client: httpx2.AsyncClient,
        auth: atlassian_ports.AtlassianAuth,
    ) -> atlassian_client.AtlassianClient:
        return atlassian_client.AtlassianClient(http=client, auth=auth)

    @dishka.provide
    def provide_connection_test_service(
        self,
        config: app_config.AppConfig,
        client: httpx2.AsyncClient,
        oauth: oauth_client.OAuthClient,
    ) -> connection_test_service.AtlassianConnectionTestService:
        return connection_test_service.AtlassianConnectionTestService(
            http=client,
            oauth=oauth,
            api_base=config.atlassian_config.api_base,
        )

    @dishka.provide
    def provide_allowlist_source(
        self,
        config: app_config.AppConfig,
        static: guard_module.StaticAllowlistSource,
        store: atlassian_ports.SpaceAccessRequestStore,
        principal: principal_module.Principal,
    ) -> guard_module.AllowlistSource:
        """The one place RESOURCE_GUARD_MODE is read: "config_list"
        (default) enforces the static allowlist from settings; "allow_list"
        enforces the calling user's approved access requests, bound here so
        the policy never sees a user id. The setting is a Literal, so there
        is no third case."""
        if config.resource_guard_mode == "allow_list":
            return approved_requests_source.ApprovedRequestsAllowlistSource(
                principal.user_id, store
            )
        return static

    @dishka.provide
    def provide_access_policy(
        self, source: guard_module.AllowlistSource
    ) -> guard_module.AccessPolicy:
        return guard_module.AllowlistAccessPolicy(source)

    @dishka.provide
    def provide_jira_service(
        self,
        client: atlassian_client.AtlassianClient,
        policy: guard_module.AccessPolicy,
    ) -> jira_service.JiraService:
        return jira_service.JiraService(client=client, policy=policy)

    @dishka.provide
    def provide_confluence_service(
        self,
        client: atlassian_client.AtlassianClient,
        policy: guard_module.AccessPolicy,
    ) -> confluence_service.ConfluenceService:
        return confluence_service.ConfluenceService(client=client, policy=policy)
