"""REST-surface identity resolution strategies, selected by REST_AUTH_MODE.

- trusted (default): the portal asserts the caller via TRUSTED_USER_HEADER.
  Used by the token-management surface (POST/GET/DELETE /tokens), where a
  caller who hasn't minted a PAT yet has nothing else to present. Only safe
  when the surface it guards is reachable solely from the portal's network.
- token: the caller presents one of atlassian-mcp's own personal access tokens,
  the same way /mcp does.
"""

import abc

import fastapi

from app.auth import principal as principal_module
from app.auth import verifier as verifier_port
from app.identity import service as identity_service


class UserResolver(abc.ABC):
    @abc.abstractmethod
    async def resolve(self, request: fastapi.Request) -> principal_module.Principal: ...


class TrustedHeaderUserResolver(UserResolver):
    def __init__(
        self, header_name: str, identity: identity_service.IdentityService
    ) -> None:
        self._header_name = header_name
        self._identity = identity

    async def resolve(self, request: fastapi.Request) -> principal_module.Principal:
        # The header value is the portal-asserted user email, used verbatim
        # as this server's user_id — no separate id is minted. get_or_create
        # records it the first time it's seen and looks it up on every call
        # after that, so by the time a router reads principal.user_id it is
        # already resolved.
        user_id = request.headers.get(self._header_name)
        if not user_id:
            raise fastapi.HTTPException(
                status_code=400,
                detail=f"Missing required {self._header_name} header.",
            )

        user = await self._identity.get_or_create(user_id)
        return principal_module.Principal(user_id=user.user_id, email=user.email)


class PersonalTokenUserResolver(UserResolver):
    def __init__(self, verifier: verifier_port.TokenVerifier) -> None:
        self._verifier = verifier

    async def resolve(self, request: fastapi.Request) -> principal_module.Principal:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise fastapi.HTTPException(
                status_code=401,
                detail="Missing or invalid Authorization header.",
            )

        token = auth_header.removeprefix("Bearer ").strip()
        verified = await self._verifier.verify(token)
        if verified is None:
            raise fastapi.HTTPException(
                status_code=401, detail="Invalid, expired, or revoked token."
            )

        claims = verified.claims
        return principal_module.Principal(
            user_id=str(claims["sub"]),
            email=claims.get("email"),
            label=claims.get("label"),
            token_id=claims.get("token_id"),
        )
