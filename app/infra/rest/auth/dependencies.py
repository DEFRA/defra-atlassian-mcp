"""The REST dependencies every router uses for identity — handlers receive a
Principal, never a token or a raw header value.
"""

import dishka
import fastapi
from dishka.integrations import fastapi as dishka_fastapi

from app import config as app_config
from app.auth import principal as principal_module
from app.identity import service as identity_service
from app.infra.rest.auth import resolver as resolver_module


@dishka_fastapi.inject
async def get_principal(
    request: fastapi.Request,
    resolver: dishka.FromDishka[resolver_module.UserResolver],
) -> principal_module.Principal:
    return await resolver.resolve(request)


@dishka_fastapi.inject
async def get_trusted_principal(
    request: fastapi.Request,
    identity: dishka.FromDishka[identity_service.IdentityService],
    identity_config: dishka.FromDishka[app_config.IdentityConfig],
) -> principal_module.Principal:
    """Always resolves via the trusted header, independent of REST_AUTH_MODE.

    Used only by the token-management surface (POST/GET/DELETE /tokens): a
    caller who has not minted a personal access token yet has nothing else
    to present, so that surface cannot itself be gated by REST_AUTH_MODE=token
    without a chicken-and-egg problem.
    """
    trusted = resolver_module.TrustedHeaderUserResolver(
        identity_config.trusted_user_header, identity
    )
    return await trusted.resolve(request)
