import dishka
import fastmcp
from fastmcp.server import dependencies as fastmcp_deps

from app import config as app_config
from app.auth import principal as principal_module
from app.auth import verifier as verifier_port
from app.identity import service as identity_service
from app.infra.auth import personal_token
from app.infra.rest.auth import resolver as resolver_module


class AuthProvider(dishka.Provider):
    @dishka.provide(scope=dishka.Scope.APP)
    def provide_token_verifier(
        self,
        tokens: identity_service.PersonalTokenService,
        users: identity_service.IdentityService,
    ) -> verifier_port.TokenVerifier:
        return personal_token.PersonalTokenVerifier(tokens, users)

    @dishka.provide(scope=dishka.Scope.APP)
    def provide_user_resolver(
        self,
        identity_config: app_config.IdentityConfig,
        identity: identity_service.IdentityService,
        token_verifier: verifier_port.TokenVerifier,
    ) -> resolver_module.UserResolver:
        """Choose how the REST surface authenticates, per REST_AUTH_MODE:

        - trusted (default) — trust the network-asserted caller header.
        - token — validate a presented personal access token, same as /mcp.

        The token-management surface (POST/GET/DELETE /tokens) does not use
        this — it always resolves via the trusted header (see
        app.infra.rest.auth.dependencies.get_trusted_principal), since a
        caller who has not minted a token yet has nothing else to present.
        """
        if identity_config.rest_auth_mode == "token":
            return resolver_module.PersonalTokenUserResolver(token_verifier)
        return resolver_module.TrustedHeaderUserResolver(
            identity_config.trusted_user_header, identity
        )

    @dishka.provide(scope=dishka.Scope.REQUEST)
    def provide_principal(
        self,
        _ctx: fastmcp.Context,  # noqa: ARG002 -- binds this provider to the MCP request scope
    ) -> principal_module.Principal:
        """Build the caller Principal for an MCP tool from the access token
        FastMCP already verified as transport auth (see app.infra.mcp.auth).

        REST uses app.infra.rest.auth.dependencies.get_principal instead;
        both surfaces converge on the same Principal shape, built from the
        same claims, so tools and routers never see a token or a claim name.
        """
        access = fastmcp_deps.get_access_token()
        if access is None:
            msg = "MCP request has no authenticated access token."
            raise RuntimeError(msg)

        claims = access.claims or {}
        return principal_module.Principal(
            user_id=str(claims.get("sub", access.client_id)),
            email=claims.get("email"),
            label=claims.get("label"),
            token_id=claims.get("token_id"),
        )
