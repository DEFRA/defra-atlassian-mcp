import fastapi
import pydantic
from dishka.integrations import fastapi as dishka_fastapi
from pydantic import alias_generators

from app import config as app_config
from app.auth import principal as principal_module
from app.infra.rest.auth import dependencies as auth_deps
from app.integration.atlassian import access_request_service, exceptions
from app.integration.atlassian import guard as guard_module
from app.integration.atlassian import models as access_request_models

router = fastapi.APIRouter()


class ConfigAllowListResponse(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(
        alias_generator=alias_generators.to_camel, populate_by_name=True
    )

    mode: str
    jira_projects: list[str]
    confluence_spaces: list[str]


@router.get("/resource-guard/allowed-spaces")
@dishka_fastapi.inject
async def get_config_allow_list(
    _principal: principal_module.Principal = fastapi.Depends(auth_deps.get_principal),
    config: dishka_fastapi.FromDishka[app_config.AppConfig] = ...,  # type: ignore[assignment]
    allow_list: dishka_fastapi.FromDishka[guard_module.ConfigAllowList] = ...,  # type: ignore[assignment]
) -> ConfigAllowListResponse:
    """The hand-managed, per-product allow list
    (RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS / RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES),
    for the portal to display to users. Independent of the
    SpaceAccessRequest workflow below -- these values are only actually
    enforced when mode == "config_list"."""
    return ConfigAllowListResponse(
        mode=config.resource_guard_mode,
        jira_projects=sorted(allow_list.jira_projects),
        confluence_spaces=sorted(allow_list.confluence_spaces),
    )


class DecisionPayload(pydantic.BaseModel):
    """One product's decision. The IAO decides Jira and Confluence
    separately, so approving a space for both is two calls and the product
    not named here is left exactly as it was."""

    model_config = pydantic.ConfigDict(
        alias_generator=alias_generators.to_camel, populate_by_name=True
    )

    product: access_request_models.Product
    decision_reason: str


class ApprovalPayload(DecisionPayload):
    data_handling_form_ref: str | None = None
    risk_assessment_ref: str | None = None


@router.get("/access-requests")
@dishka_fastapi.inject
async def list_pending_access_requests(
    _reviewer: principal_module.Principal = fastapi.Depends(auth_deps.get_principal),
    status: str | None = None,  # noqa: ARG001
    service: dishka_fastapi.FromDishka[
        access_request_service.SpaceAccessRequestService
    ] = ...,  # type: ignore[assignment]
) -> list[access_request_models.SpaceAccessRequest]:
    """List space access requests awaiting IAO review — those with at least
    one product still pending.

    Reachable only by the portal — the IAO reviews and decides through the
    portal, which calls these endpoints on their behalf. ``status`` is
    accepted because the portal sends ``?status=pending``, but this route
    only ever returns pending requests, so it is not applied.
    """
    return await service.list_pending()


@router.post("/access-requests/{request_id}/approve")
@dishka_fastapi.inject
async def approve_access_request(
    request_id: str,
    payload: ApprovalPayload,
    reviewer: principal_module.Principal = fastapi.Depends(auth_deps.get_principal),
    service: dishka_fastapi.FromDishka[
        access_request_service.SpaceAccessRequestService
    ] = ...,  # type: ignore[assignment]
) -> access_request_models.SpaceAccessRequest:
    """Approve one product on a pending access request, recording the IAO's
    decision reason plus references to the data-handling form and risk
    assessment."""
    try:
        return await service.approve(
            request_id,
            payload.product,
            reviewer.user_id,
            payload.decision_reason,
            payload.data_handling_form_ref,
            payload.risk_assessment_ref,
        )
    except exceptions.AccessRequestNotFoundError as exc:
        raise fastapi.HTTPException(status_code=404, detail=str(exc)) from exc
    except exceptions.AccessRequestAlreadyDecidedError as exc:
        raise fastapi.HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/access-requests/{request_id}/reject")
@dishka_fastapi.inject
async def reject_access_request(
    request_id: str,
    payload: DecisionPayload,
    reviewer: principal_module.Principal = fastapi.Depends(auth_deps.get_principal),
    service: dishka_fastapi.FromDishka[
        access_request_service.SpaceAccessRequestService
    ] = ...,  # type: ignore[assignment]
) -> access_request_models.SpaceAccessRequest:
    """Reject one product on a pending access request, recording the IAO's
    decision reason."""
    try:
        return await service.reject(
            request_id,
            payload.product,
            reviewer.user_id,
            payload.decision_reason,
        )
    except exceptions.AccessRequestNotFoundError as exc:
        raise fastapi.HTTPException(status_code=404, detail=str(exc)) from exc
    except exceptions.AccessRequestAlreadyDecidedError as exc:
        raise fastapi.HTTPException(status_code=409, detail=str(exc)) from exc
