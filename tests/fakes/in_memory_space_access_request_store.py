from app.integration.atlassian import models, ports


class InMemorySpaceAccessRequestStore(ports.SpaceAccessRequestStore):
    def __init__(self) -> None:
        self._store: dict[str, models.SpaceAccessRequest] = {}

    async def create(self, request: models.SpaceAccessRequest) -> None:
        self._store[request.id] = request

    async def get(self, request_id: str) -> models.SpaceAccessRequest | None:
        return self._store.get(request_id)

    async def get_for_user_and_space(
        self, user_id: str, space_key: str
    ) -> models.SpaceAccessRequest | None:
        return next(
            (
                r
                for r in self._store.values()
                if r.user_id == user_id and r.space_key == space_key
            ),
            None,
        )

    async def list_for_user(self, user_id: str) -> list[models.SpaceAccessRequest]:
        return [r for r in self._store.values() if r.user_id == user_id]

    async def list_pending(self) -> list[models.SpaceAccessRequest]:
        return [r for r in self._store.values() if r.has_pending_product()]

    async def update(self, request: models.SpaceAccessRequest) -> None:
        self._store[request.id] = request

    async def is_approved(
        self, user_id: str, space_key: str, product: models.Product
    ) -> bool:
        request = await self.get_for_user_and_space(user_id, space_key)
        return request is not None and request.is_approved_for(product)
