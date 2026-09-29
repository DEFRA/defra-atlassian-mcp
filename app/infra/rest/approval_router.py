import fastapi
import pydantic
from dishka.integrations import fastapi as dishka_fastapi
from pydantic import alias_generators

from app.auth import principal as principal_module
from app.infra.rest.auth import dependencies as auth_deps
from app.integration.atlassian import access_request_service, exceptions
from app.integration.atlassian import models as access_request_models

router = fastapi.APIRouter()


class RequestSpaceAccessPayload(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(
        alias_generator=alias_generators.to_camel, populate_by_name=True
    )

    space_key: str
    iao: str
    reason: str
    products: list[access_request_models.Product] = pydantic.Field(min_length=1)
    # The portal sends the signed-in user's email in the body as well as in
    # the trusted header. The header is the credential, so this is accepted
    # for compatibility and never read.
    user_id: str | None = None


@router.post("/spaces", status_code=201)
@dishka_fastapi.inject
async def request_space_access(
    payload: RequestSpaceAccessPayload,
    principal: principal_module.Principal = fastapi.Depends(auth_deps.get_principal),
    service: dishka_fastapi.FromDishka[
        access_request_service.SpaceAccessRequestService
    ] = ...,  # type: ignore[assignment]
) -> access_request_models.SpaceAccessRequest:
    try:
        return await service.request_access(
            principal.user_id,
            payload.space_key,
            payload.iao,
            payload.reason,
            payload.products,
        )
    except exceptions.AccessRequestAlreadyOpenError as exc:
        raise fastapi.HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/spaces/{space_key}")
@dishka_fastapi.inject
async def get_space_access_request(
    space_key: str,
    principal: principal_module.Principal = fastapi.Depends(auth_deps.get_principal),
    service: dishka_fastapi.FromDishka[
        access_request_service.SpaceAccessRequestService
    ] = ...,  # type: ignore[assignment]
) -> access_request_models.SpaceAccessRequest:
    request = await service.get_for_user(principal.user_id, space_key)
    if request is None:
        raise fastapi.HTTPException(
            status_code=404, detail="Space access request not found."
        )
    return request
