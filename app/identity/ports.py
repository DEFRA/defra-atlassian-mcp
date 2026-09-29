import abc
import datetime

from app.identity import models


class UserStore(abc.ABC):
    @abc.abstractmethod
    async def get_by_user_id(self, user_id: str) -> models.User | None: ...

    @abc.abstractmethod
    async def get_or_create(self, user_id: str) -> models.User: ...


class PersonalAccessTokenStore(abc.ABC):
    @abc.abstractmethod
    async def create(self, token: models.PersonalAccessToken) -> None: ...

    @abc.abstractmethod
    async def get_by_hash(
        self, token_hash: str
    ) -> models.PersonalAccessToken | None: ...

    @abc.abstractmethod
    async def get(self, token_id: str) -> models.PersonalAccessToken | None: ...

    @abc.abstractmethod
    async def list_for_user(self, user_id: str) -> list[models.PersonalAccessToken]: ...

    @abc.abstractmethod
    async def revoke(self, token_id: str) -> None: ...

    @abc.abstractmethod
    async def touch_last_used(self, token_id: str, when: datetime.datetime) -> None: ...
