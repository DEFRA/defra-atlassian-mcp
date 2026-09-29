"""The concrete TokenVerifier: atlassian-mcp mints its own personal access
tokens, so verification is a lookup against PersonalTokenService rather than
a signature check against an external IdP's key. This is the only
implementation of app.auth.verifier.TokenVerifier in the app — both /mcp
(app.infra.mcp.auth) and REST (app.infra.rest.auth.resolver) bind to it.
"""

from app.auth import verifier
from app.identity import exceptions
from app.identity import service as identity_service


class PersonalTokenVerifier:
    def __init__(
        self,
        tokens: identity_service.PersonalTokenService,
        users: identity_service.IdentityService,
    ) -> None:
        self._tokens = tokens
        self._users = users

    async def verify(self, token: str) -> verifier.VerifiedToken | None:
        try:
            record = await self._tokens.verify(token)
        except (
            exceptions.UnknownTokenError,
            exceptions.TokenExpiredError,
            exceptions.TokenRevokedError,
        ):
            return None

        user = await self._users.get_by_user_id(record.user_id)
        if user is None:
            return None

        return verifier.VerifiedToken(
            claims={
                "sub": user.user_id,
                "email": user.email,
                "label": record.label,
                "token_id": record.id,
            }
        )
