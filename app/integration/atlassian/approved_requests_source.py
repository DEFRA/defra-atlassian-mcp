from app.integration.atlassian import models, ports


class ApprovedRequestsAllowlistSource:
    """AllowlistSource over one user's approved space access requests
    (RESOURCE_GUARD_MODE=allow_list). HTTP only: built per request, bound to
    the calling user, so the policy and services never see a user id.

    Each check is a single SpaceAccessRequestStore.is_approved lookup.
    """

    def __init__(self, user_id: str, store: ports.SpaceAccessRequestStore) -> None:
        self._user_id = user_id
        self._store = store

    async def contains(self, product: models.Product, key: str) -> bool:
        return await self._store.is_approved(self._user_id, key, product)

    def denial_message(self, product: models.Product, key: str) -> str:
        return (
            f"No approved access request for {key} "
            f"in {product.value}. Request access in the portal first."
        )
