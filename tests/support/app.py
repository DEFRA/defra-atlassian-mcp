"""One factory for the real app over a test container, replacing the four
hand-rolled ~50-line `_build_app()` copies and their three duplicated
`_override_get_principal`s that used to live in tests/unit/infra/rest/.

The thin-override pattern (see docs/python-test-migration-playbook.md §7):
take the real provider list, in the same order production uses, and
substitute only the I/O edges -- config, the five store ports, and the
request-scoped httpx2 client. `dishka.provide(override=True)` replaces a
factory *and drops its dependencies from the graph*, which is what removes
AsyncMongoClient/AsyncDatabase without a fake database object: nothing left
in the graph asks for them once every Mongo-backed store is overridden, so
InfrastructureProvider (whose only other export is a CA-cert dict nothing
else needs) is left out entirely rather than included and drained.

Everything else -- IdentityService, PersonalTokenService,
PersonalTokenVerifier, UserResolver, OAuthClient, LinkingService,
the Jira and Confluence services, SpaceAccessRequestService and SpaceGuard --
stays real, wired from the real provider list.
"""

import collections.abc
import contextlib
import dataclasses

import dishka
import fastapi.testclient
import fastmcp
import fastmcp.client.transports as fastmcp_transports
import httpx2
import pydantic
from dishka.integrations import fastapi as dishka_fastapi

from app import config as app_config
from app.di.providers import auth, identity, integration, request_scope, settings
from app.entrypoints import http as entrypoint
from app.identity import ports as identity_ports
from app.identity import service as identity_service
from app.infra.mcp import dishka_inject
from app.infra.mcp import mcp as mcp_module
from app.infra.mcp import tools as atlassian_tools
from app.infra.rest.auth import dependencies as auth_deps
from app.integration.atlassian import ports as atlassian_ports
from app.integration.linking import models as linking_models
from app.integration.linking import ports as linking_ports
from tests.fakes import (
    httpx_helpers,
    in_memory_identity_store,
    in_memory_oauth_state_store,
    in_memory_space_access_request_store,
    in_memory_token_store,
)


class TestOverrides(dishka.Provider):
    """APP-scoped I/O-edge substitutions, appended after the real providers."""

    scope = dishka.Scope.APP

    def __init__(
        self,
        *,
        cfg: app_config.AppConfig,
        tokens: linking_ports.TokenStore,
        states: linking_ports.OAuthStateStore,
        access_requests: atlassian_ports.SpaceAccessRequestStore,
        users: identity_ports.UserStore,
        pats: identity_ports.PersonalAccessTokenStore,
        transport: httpx_helpers.MockTransport,
    ) -> None:
        super().__init__()
        self._cfg = cfg
        self._tokens = tokens
        self._states = states
        self._access_requests = access_requests
        self._users = users
        self._pats = pats
        self._transport = transport

    @dishka.provide(override=True)
    def provide_config(self) -> app_config.AppConfig:
        return self._cfg

    @dishka.provide(override=True)
    def provide_token_store(self) -> linking_ports.TokenStore:
        return self._tokens

    @dishka.provide(override=True)
    def provide_state_store(self) -> linking_ports.OAuthStateStore:
        return self._states

    @dishka.provide(override=True)
    def provide_access_request_store(self) -> atlassian_ports.SpaceAccessRequestStore:
        return self._access_requests

    @dishka.provide(override=True)
    def provide_user_store(self) -> identity_ports.UserStore:
        return self._users

    @dishka.provide(override=True)
    def provide_pat_store(self) -> identity_ports.PersonalAccessTokenStore:
        return self._pats

    @dishka.provide(scope=dishka.Scope.REQUEST, override=True)
    def provide_httpx_client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=self._transport)


@dataclasses.dataclass
class Overrides:
    """Handed back to the test so it can seed state through the same fakes
    the app is wired to, and inspect what went out to the vendor."""

    cfg: app_config.AppConfig
    tokens: linking_ports.TokenStore
    states: linking_ports.OAuthStateStore
    access_requests: atlassian_ports.SpaceAccessRequestStore
    users: identity_ports.UserStore
    pats: identity_ports.PersonalAccessTokenStore
    transport: httpx_helpers.MockTransport


def real_config(**field_overrides: object) -> app_config.AppConfig:
    """A real AppConfig built from fixed test values, mirroring conftest's
    fake_config -- no MagicMock, no env var coupling."""
    atlassian_cfg = app_config.AtlassianConfig.model_construct(
        auth_base="https://auth.atlassian.com",
        api_base="https://api.atlassian.com",
        client_id="test-client-id",
        client_secret=pydantic.SecretStr("test-secret"),
        redirect_uri="http://portal.example.com/account/atlassian-linking/callback",
    )
    defaults: dict[str, object] = {
        "base_url": "http://example.com",
        "resource_guard_mode": "allow_all",
        "resource_guard_allowed_jira_projects": "",
        "resource_guard_allowed_confluence_spaces": "",
        "atlassian_config": atlassian_cfg,
    }
    defaults.update(field_overrides)
    return app_config.AppConfig.model_construct(**defaults)


def _build_container(
    *,
    cfg: app_config.AppConfig,
    responses: list[httpx2.Response | Exception],
    tokens: linking_ports.TokenStore | None,
    states: linking_ports.OAuthStateStore | None,
    access_requests: atlassian_ports.SpaceAccessRequestStore | None,
    users: identity_ports.UserStore | None,
    pats: identity_ports.PersonalAccessTokenStore | None,
) -> tuple[dishka.AsyncContainer, Overrides]:
    transport = httpx_helpers.MockTransport(responses)
    overrides = Overrides(
        cfg=cfg,
        tokens=tokens or in_memory_token_store.InMemoryTokenStore(),
        states=states or in_memory_oauth_state_store.InMemoryOAuthStateStore(),
        access_requests=(
            access_requests
            or in_memory_space_access_request_store.InMemorySpaceAccessRequestStore()
        ),
        users=users or in_memory_identity_store.InMemoryUserStore(),
        pats=pats or in_memory_identity_store.InMemoryPersonalAccessTokenStore(),
        transport=transport,
    )

    # Same provider list and order as app.di.container.build_async_container
    # (minus InfrastructureProvider -- see module docstring), with
    # TestOverrides appended last so its override=True bindings win.
    container = dishka.make_async_container(
        settings.SettingsProvider(),
        identity.IdentityProvider(),
        auth.AuthProvider(),
        integration.AtlassianProvider(),
        request_scope.RequestScopeProvider(),
        dishka_fastapi.FastapiProvider(),
        dishka_inject.FastMCPProvider(),
        TestOverrides(
            cfg=overrides.cfg,
            tokens=overrides.tokens,
            states=overrides.states,
            access_requests=overrides.access_requests,
            users=overrides.users,
            pats=overrides.pats,
            transport=transport,
        ),
    )
    return container, overrides


@contextlib.contextmanager
def rest_client(
    *,
    cfg: app_config.AppConfig | None = None,
    responses: list[httpx2.Response | Exception] | None = None,
    tokens: linking_ports.TokenStore | None = None,
    states: linking_ports.OAuthStateStore | None = None,
    access_requests: atlassian_ports.SpaceAccessRequestStore | None = None,
    users: identity_ports.UserStore | None = None,
    pats: identity_ports.PersonalAccessTokenStore | None = None,
    principal: object | None = None,
    **cfg_overrides: object,
) -> collections.abc.Iterator[tuple[fastapi.testclient.TestClient, Overrides]]:
    """Drive the real create_app over a test container.

    With no `principal`, requests authenticate for real through the app's
    own UserResolver (TrustedHeaderUserResolver by default -- send an
    X-User-Id header). Pass `principal` only when a test genuinely wants to
    skip that resolution, via app.dependency_overrides[get_principal] --
    never a patch.
    """
    resolved_cfg = cfg or real_config(**cfg_overrides)
    container, overrides = _build_container(
        cfg=resolved_cfg,
        responses=responses or [],
        tokens=tokens,
        states=states,
        access_requests=access_requests,
        users=users,
        pats=pats,
    )

    app = entrypoint.create_app(resolved_cfg, container=container)
    if principal is not None:
        app.dependency_overrides[auth_deps.get_principal] = lambda: principal

    with fastapi.testclient.TestClient(app) as client:
        yield client, overrides


@contextlib.asynccontextmanager
async def mcp_registry_client(
    *,
    cfg: app_config.AppConfig | None = None,
    **cfg_overrides: object,
) -> collections.abc.AsyncIterator[fastmcp.Client]:
    """A cheap in-memory `fastmcp.Client` (FastMCPTransport -- no sockets, no
    HTTP, no auth) for registration/schema/description checks that don't
    need to actually call a tool. This transport cannot carry auth at all,
    so use `mcp_client` instead for anything that calls a tool."""
    resolved_cfg = cfg or real_config(**cfg_overrides)
    container, _overrides = _build_container(
        cfg=resolved_cfg,
        responses=[],
        tokens=None,
        states=None,
        access_requests=None,
        users=None,
        pats=None,
    )
    async with container:
        app = mcp_module.build_mcp_app(container, resolved_cfg)
        atlassian_tools.register_tools(app)
        async with fastmcp.Client(app) as client:
            yield client


def _asgi_httpx_client_factory(
    app: fastapi.FastAPI,
) -> collections.abc.Callable[..., httpx2.AsyncClient]:
    def factory(
        *,
        headers: dict[str, str] | None = None,
        auth: httpx2.Auth | None = None,
        follow_redirects: bool = True,
        timeout: httpx2.Timeout | None = None,
        **_kwargs: object,
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
        )

    return factory


@contextlib.asynccontextmanager
async def mcp_client(
    *,
    cfg: app_config.AppConfig | None = None,
    responses: list[httpx2.Response | Exception] | None = None,
    tokens: linking_ports.TokenStore | None = None,
    states: linking_ports.OAuthStateStore | None = None,
    access_requests: atlassian_ports.SpaceAccessRequestStore | None = None,
    users: identity_ports.UserStore | None = None,
    pats: identity_ports.PersonalAccessTokenStore | None = None,
    atlassian_token: str | None = None,
    user_id: str = "mcp-test-user@example.com",
    **cfg_overrides: object,
) -> collections.abc.AsyncIterator[tuple[fastmcp.Client, Overrides, str]]:
    """Drive the real MCP surface -- registration through to a tool call --
    over ASGI (httpx2.ASGITransport wrapping the real create_app), so
    transport-level bearer auth is enforced for real.

    The in-memory FastMCPTransport (`fastmcp.Client(fastmcp_app)`) is fine
    for list_tools()/schema inspection, but it cannot carry auth at all --
    `transport._set_auth(token)` raises `ValueError: This transport does
    not support auth` -- so it can only ever exercise a tool's
    no-Principal failure path, never a success. Going over ASGI instead
    means every layer is real: FastMCP's auth provider verifies the token,
    dishka_inject builds the real Principal, and the tool runs against the
    real Jira and Confluence services.

    Mints a real personal access token for a freshly-resolved user and
    passes it as the client's bearer auth. If `atlassian_token` is given, it is
    stored for that same user first, so a tool's happy path needs no
    further setup. Yields (client, overrides, user_id) with the client
    already connected.
    """
    resolved_cfg = cfg or real_config(**cfg_overrides)
    container, overrides = _build_container(
        cfg=resolved_cfg,
        responses=responses or [],
        tokens=tokens,
        states=states,
        access_requests=access_requests,
        users=users,
        pats=pats,
    )

    identity_svc = identity_service.IdentityService(overrides.users)
    user = await identity_svc.get_or_create(user_id)
    if atlassian_token is not None:
        await overrides.tokens.store_tokens(
            user.user_id,
            linking_models.AtlassianToken(
                access_token=atlassian_token,
                refresh_token="test-refresh-token",  # noqa: S106
                cloud_id="test-cloud-id",
            ),
        )

    ic = resolved_cfg.identity_config
    token_svc = identity_service.PersonalTokenService(
        overrides.pats,
        default_ttl_days=ic.default_ttl_days,
        max_ttl_days=ic.max_ttl_days,
        last_used_throttle_seconds=ic.last_used_throttle_seconds,
    )
    _, secret = await token_svc.mint(user.user_id, "mcp test client")

    app = entrypoint.create_app(resolved_cfg, container=container)
    mcp_transport = fastmcp_transports.StreamableHttpTransport(
        url="http://testserver/mcp/",
        auth=secret,
        httpx_client_factory=_asgi_httpx_client_factory(app),
    )

    async with (
        app.router.lifespan_context(app),
        fastmcp.Client(mcp_transport) as client,
    ):
        yield client, overrides, user.user_id


def seed[T, **P](
    client: fastapi.testclient.TestClient,
    coro_fn: collections.abc.Callable[P, collections.abc.Awaitable[T]],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Run an async setup call (e.g. `overrides.states.issue(...)`) on the
    TestClient's own portal loop, never a bare `asyncio.run()`. A plain dict
    fake has no loop affinity so seeding off-loop works today by luck; it
    breaks the moment a fake holds an asyncio.Lock or becomes a real async
    driver."""
    return client.portal.call(coro_fn, *args, **kwargs)
