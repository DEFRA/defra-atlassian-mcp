"""End-to-end wiring test for the token-management surface: mint via the
real IdentityService/PersonalTokenService/PersonalTokenVerifier stack
(storage faked, everything else real), then use the minted token against a
protected route through the same get_principal dependency /mcp and the
other REST routers rely on. This is the thing unit tests on individual
pieces can't prove: that the DI graph actually hangs together end to end.
"""

import collections.abc
import contextlib

import dishka
import fastapi
import fastapi.testclient
from dishka.integrations import fastapi as dishka_fastapi

from app import config as app_config
from app.auth import principal as principal_module
from app.auth import verifier as verifier_port
from app.common import tracing
from app.identity import ports
from app.identity import service as identity_service
from app.infra.auth import personal_token
from app.infra.rest import token_router
from app.infra.rest.auth import dependencies as auth_deps
from app.infra.rest.auth import resolver as resolver_module
from tests.fakes import in_memory_identity_store


class _Provider(dishka.Provider):
    scope = dishka.Scope.APP

    @dishka.provide
    def provide_user_store(self) -> ports.UserStore:
        return in_memory_identity_store.InMemoryUserStore()

    @dishka.provide
    def provide_pat_store(self) -> ports.PersonalAccessTokenStore:
        return in_memory_identity_store.InMemoryPersonalAccessTokenStore()

    @dishka.provide
    def provide_identity_service(
        self, users: ports.UserStore
    ) -> identity_service.IdentityService:
        return identity_service.IdentityService(users)

    @dishka.provide
    def provide_token_service(
        self, tokens: ports.PersonalAccessTokenStore
    ) -> identity_service.PersonalTokenService:
        return identity_service.PersonalTokenService(
            tokens,
            default_ttl_days=90,
            max_ttl_days=365,
            last_used_throttle_seconds=300,
        )

    @dishka.provide
    def provide_token_verifier(
        self,
        tokens: identity_service.PersonalTokenService,
        users: identity_service.IdentityService,
    ) -> verifier_port.TokenVerifier:
        return personal_token.PersonalTokenVerifier(tokens, users)

    @dishka.provide
    def provide_user_resolver(
        self, token_verifier: verifier_port.TokenVerifier
    ) -> resolver_module.UserResolver:
        """The /protected route below authenticates with a bearer token, same
        as /mcp -- REST_AUTH_MODE=token, not the default trusted-header mode
        /tokens itself uses.
        """
        return resolver_module.PersonalTokenUserResolver(token_verifier)

    @dishka.provide
    def provide_identity_config(self) -> app_config.IdentityConfig:
        return app_config.IdentityConfig.model_construct()


def _build_app() -> fastapi.FastAPI:
    container = dishka.make_async_container(
        _Provider(), dishka_fastapi.FastapiProvider()
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: fastapi.FastAPI) -> collections.abc.AsyncGenerator[None]:
        async with container:
            app.state.dishka_container = container
            yield

    app = fastapi.FastAPI(lifespan=lifespan)
    app.add_middleware(tracing.ContainerMiddleware)
    app.add_middleware(
        tracing.TraceIdMiddleware,
        cfg=app_config.AppConfig.model_construct(tracing_header="x-cdp-request-id"),
    )
    app.include_router(token_router.router, prefix="/tokens")

    @app.get("/protected")
    @dishka_fastapi.inject
    async def protected(
        principal: principal_module.Principal = fastapi.Depends(
            auth_deps.get_principal
        ),
    ) -> dict[str, str]:
        return {"user_id": principal.user_id}

    return app


class TestPersonalTokens:
    def test_mint_use_and_revoke_end_to_end(self) -> None:
        with fastapi.testclient.TestClient(_build_app()) as client:
            mint = client.post(
                "/tokens",
                json={"label": "Claude Code"},
                headers={"X-User-Id": "dev@example.com"},
            )
            assert mint.status_code == 201
            body = mint.json()
            assert body["token"].startswith("amcp_")
            secret = body["token"]

            protected = client.get(
                "/protected", headers={"Authorization": f"Bearer {secret}"}
            )
            assert protected.status_code == 200
            assert protected.json()["user_id"] == "dev@example.com"

            listing = client.get("/tokens", headers={"X-User-Id": "dev@example.com"})
            assert listing.status_code == 200
            assert len(listing.json()) == 1
            assert "token" not in listing.json()[0]

            revoke = client.delete(
                f"/tokens/{body['id']}", headers={"X-User-Id": "dev@example.com"}
            )
            assert revoke.status_code == 204

            after_revoke = client.get(
                "/protected", headers={"Authorization": f"Bearer {secret}"}
            )
            assert after_revoke.status_code == 401

    def test_mint_requires_the_trusted_header(self) -> None:
        with fastapi.testclient.TestClient(_build_app()) as client:
            response = client.post("/tokens", json={"label": "Claude Code"})
            assert response.status_code == 400

    def test_different_users_get_independent_token_lists(self) -> None:
        with fastapi.testclient.TestClient(_build_app()) as client:
            client.post(
                "/tokens", json={"label": "a"}, headers={"X-User-Id": "a@example.com"}
            )
            client.post(
                "/tokens", json={"label": "b"}, headers={"X-User-Id": "b@example.com"}
            )

            a_tokens = client.get(
                "/tokens", headers={"X-User-Id": "a@example.com"}
            ).json()
            b_tokens = client.get(
                "/tokens", headers={"X-User-Id": "b@example.com"}
            ).json()

            assert len(a_tokens) == 1
            assert len(b_tokens) == 1
            assert a_tokens[0]["label"] == "a"
            assert b_tokens[0]["label"] == "b"

    def test_revoking_another_users_token_is_not_found(self) -> None:
        with fastapi.testclient.TestClient(_build_app()) as client:
            mint = client.post(
                "/tokens", json={"label": "a"}, headers={"X-User-Id": "a@example.com"}
            )
            token_id = mint.json()["id"]

            response = client.delete(
                f"/tokens/{token_id}", headers={"X-User-Id": "b@example.com"}
            )
            assert response.status_code == 404
