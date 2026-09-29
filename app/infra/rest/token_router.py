"""Token lifecycle management for the portal: mint, list, and revoke this
caller's own personal access tokens.

Always authenticated via the trusted header
(app.infra.rest.auth.dependencies.get_trusted_principal), independent of
REST_AUTH_MODE — a caller who has not minted a token yet has nothing else to
present here.
"""

import datetime

import fastapi
import pydantic
from dishka.integrations import fastapi as dishka_fastapi

from app.auth import principal as principal_module
from app.identity import exceptions
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.infra.rest.auth import dependencies as auth_deps

router = fastapi.APIRouter()


class MintTokenPayload(pydantic.BaseModel):
    label: str
    ttl_days: int | None = None


class MintedTokenResponse(pydantic.BaseModel):
    """The plaintext token is returned exactly once, in this response — only
    its hash is ever persisted, so there is no other endpoint, and no other
    call to this one, that can return it again. Copy it now.
    """

    id: str
    token: str
    label: str
    expires_at: datetime.datetime


class TokenSummaryResponse(pydantic.BaseModel):
    """Note the snake_case field names: unlike the approvals and linking
    routes, the portal reads this surface unaliased."""

    id: str
    label: str
    prefix: str
    created_at: datetime.datetime
    expires_at: datetime.datetime
    last_used_at: datetime.datetime | None
    revoked_at: datetime.datetime | None
    status: identity_models.TokenStatus


@router.post("", status_code=201)
@dishka_fastapi.inject
async def mint_token(
    payload: MintTokenPayload,
    principal: principal_module.Principal = fastapi.Depends(
        auth_deps.get_trusted_principal
    ),
    tokens: dishka_fastapi.FromDishka[identity_service.PersonalTokenService] = ...,  # type: ignore[assignment]
) -> MintedTokenResponse:
    record, secret = await tokens.mint(
        principal.user_id, payload.label, payload.ttl_days
    )

    return MintedTokenResponse(
        id=record.id,
        token=secret,
        label=record.label,
        expires_at=record.expires_at,
    )


@router.get("")
@dishka_fastapi.inject
async def list_tokens(
    principal: principal_module.Principal = fastapi.Depends(
        auth_deps.get_trusted_principal
    ),
    tokens: dishka_fastapi.FromDishka[identity_service.PersonalTokenService] = ...,  # type: ignore[assignment]
) -> list[TokenSummaryResponse]:
    records = await tokens.list_for_user(principal.user_id)
    return [
        TokenSummaryResponse(
            id=record.id,
            label=record.label,
            prefix=record.prefix,
            created_at=record.created_at,
            expires_at=record.expires_at,
            last_used_at=record.last_used_at,
            revoked_at=record.revoked_at,
            status=record.status,
        )
        for record in records
    ]


@router.delete("/{token_id}", status_code=204)
@dishka_fastapi.inject
async def revoke_token(
    token_id: str,
    principal: principal_module.Principal = fastapi.Depends(
        auth_deps.get_trusted_principal
    ),
    tokens: dishka_fastapi.FromDishka[identity_service.PersonalTokenService] = ...,  # type: ignore[assignment]
) -> None:
    try:
        await tokens.revoke(principal.user_id, token_id)
    except exceptions.TokenNotFoundError as exc:
        raise fastapi.HTTPException(status_code=404, detail=str(exc)) from exc
