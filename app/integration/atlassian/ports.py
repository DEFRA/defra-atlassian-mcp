import abc

from app.integration.atlassian import models


class SpaceAccessRequestStore(abc.ABC):
    @abc.abstractmethod
    async def create(self, request: models.SpaceAccessRequest) -> None: ...

    @abc.abstractmethod
    async def get(self, request_id: str) -> models.SpaceAccessRequest | None: ...

    @abc.abstractmethod
    async def get_for_user_and_space(
        self, user_id: str, space_key: str
    ) -> models.SpaceAccessRequest | None: ...

    @abc.abstractmethod
    async def list_for_user(self, user_id: str) -> list[models.SpaceAccessRequest]: ...

    @abc.abstractmethod
    async def list_pending(self) -> list[models.SpaceAccessRequest]: ...

    @abc.abstractmethod
    async def update(self, request: models.SpaceAccessRequest) -> None: ...

    @abc.abstractmethod
    async def is_approved(
        self, user_id: str, space_key: str, product: models.Product
    ) -> bool: ...
