import datetime
from typing import Annotated

import fastapi
import pydantic
from dishka.integrations import fastapi as dishka_fastapi
from pydantic import alias_generators

from app.auth import principal as principal_module
from app.infra.rest.auth import dependencies as auth_deps
from app.integration.atlassian import (
    connection_test_service as atlassian_test_service,
)
from app.integration.linking import exceptions
from app.integration.linking import service as linking_service

router = fastapi.APIRouter()


class AtlassianCallbackQuery(pydantic.BaseModel):
    code: str
    state: str


class AuthorizationUrlResponse(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(
        alias_generator=alias_generators.to_camel,
        populate_by_name=True,
    )

    authorization_url: str


class CallbackResponse(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(
        alias_generator=alias_generators.to_camel,
        populate_by_name=True,
    )

    status: str


class TestConnectionResponse(pydantic.BaseModel):
    """The portal treats this as verified only when ``status`` is
    ``"success"``, and renders the identity from ``profile``."""

    model_config = pydantic.ConfigDict(
        alias_generator=alias_generators.to_camel,
        populate_by_name=True,
    )

    status: str
    profile: atlassian_test_service.AtlassianProfile | None = None


class AtlassianStatusResponse(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(
        alias_generator=alias_generators.to_camel,
        populate_by_name=True,
    )

    linked: bool
    access_token_expires_at: datetime.datetime | None = pydantic.Field(default=None)


@router.get("/authorization-url")
@dishka_fastapi.inject
async def get_atlassian_authorization_url(
    linking: dishka_fastapi.FromDishka[linking_service.LinkingService],
    principal: Annotated[
        principal_module.Principal, fastapi.Depends(auth_deps.get_principal)
    ],
) -> AuthorizationUrlResponse:
    url = await linking.get_authorization_url(principal.user_id)

    return AuthorizationUrlResponse(authorization_url=url)


@router.get("/callback")
@dishka_fastapi.inject
async def atlassian_callback(
    query: Annotated[AtlassianCallbackQuery, fastapi.Query()],
    linking: dishka_fastapi.FromDishka[linking_service.LinkingService],
    principal: Annotated[
        principal_module.Principal, fastapi.Depends(auth_deps.get_principal)
    ],
) -> CallbackResponse:
    """Complete the OAuth exchange.

    Atlassian redirects the browser to the *portal*, which forwards the code
    and state here — this route is never the registered redirect_uri itself.
    """
    try:
        await linking.complete_connection(principal.user_id, query.code, query.state)
    except exceptions.OAuthStateError as exc:
        raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
    except exceptions.LinkMismatchError as exc:
        raise fastapi.HTTPException(status_code=403, detail="Forbidden") from exc
    except exceptions.NoAccessibleSiteError as exc:
        raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
    except exceptions.AtlassianUnavailableError as exc:
        raise fastapi.HTTPException(
            status_code=502, detail="Atlassian is unreachable"
        ) from exc
    except exceptions.AtlassianApiError as exc:
        raise fastapi.HTTPException(status_code=502, detail=str(exc)) from exc

    return CallbackResponse(status="success")


@router.get("/status")
@dishka_fastapi.inject
async def get_atlassian_status(
    linking: dishka_fastapi.FromDishka[linking_service.LinkingService],
    principal: Annotated[
        principal_module.Principal, fastapi.Depends(auth_deps.get_principal)
    ],
) -> AtlassianStatusResponse:
    status = await linking.get_connection_status(principal.user_id)

    return AtlassianStatusResponse(
        linked=status.linked,
        access_token_expires_at=status.access_token_expires_at,
    )


@router.get("/test-connection")
@dishka_fastapi.inject
async def test_connection(
    test_svc: dishka_fastapi.FromDishka[
        atlassian_test_service.AtlassianConnectionTestService
    ],
    principal: Annotated[
        principal_module.Principal, fastapi.Depends(auth_deps.get_principal)
    ],
) -> TestConnectionResponse:
    try:
        profile = await test_svc.test_connection(principal.user_id)
    except exceptions.AtlassianTokenError as exc:
        raise fastapi.HTTPException(
            status_code=401,
            detail="No valid Atlassian access token is stored for this user",
        ) from exc
    except exceptions.AtlassianApiError as exc:
        if exc.status_code == 401:
            raise fastapi.HTTPException(
                status_code=401, detail="Atlassian has rejected the access token"
            ) from exc

        raise fastapi.HTTPException(status_code=502, detail=str(exc)) from exc
    except exceptions.AtlassianUnavailableError as exc:
        raise fastapi.HTTPException(
            status_code=502, detail="Atlassian is unreachable"
        ) from exc

    return TestConnectionResponse(status="success", profile=profile)
