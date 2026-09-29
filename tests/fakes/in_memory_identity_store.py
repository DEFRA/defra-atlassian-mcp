import datetime

from app.identity import models, ports


class InMemoryUserStore(ports.UserStore):
    def __init__(self) -> None:
        self._by_user_id: dict[str, models.User] = {}

    async def get_by_user_id(self, user_id: str) -> models.User | None:
        return self._by_user_id.get(user_id)

    async def get_or_create(self, user_id: str) -> models.User:
        existing = self._by_user_id.get(user_id)
        if existing is not None:
            return existing

        user = models.User(
            user_id=user_id,
            email=user_id,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self._by_user_id[user_id] = user
        return user


class InMemoryPersonalAccessTokenStore(ports.PersonalAccessTokenStore):
    def __init__(self) -> None:
        self._by_id: dict[str, models.PersonalAccessToken] = {}

    async def create(self, token: models.PersonalAccessToken) -> None:
        self._by_id[token.id] = token

    async def get_by_hash(self, token_hash: str) -> models.PersonalAccessToken | None:
        for token in self._by_id.values():
            if token.token_hash == token_hash:
                return token
        return None

    async def get(self, token_id: str) -> models.PersonalAccessToken | None:
        return self._by_id.get(token_id)

    async def list_for_user(self, user_id: str) -> list[models.PersonalAccessToken]:
        return [t for t in self._by_id.values() if t.user_id == user_id]

    async def revoke(self, token_id: str) -> None:
        token = self._by_id.get(token_id)
        if token is not None:
            self._by_id[token_id] = token.model_copy(
                update={"revoked_at": datetime.datetime.now(datetime.UTC)}
            )

    async def touch_last_used(self, token_id: str, when: datetime.datetime) -> None:
        token = self._by_id.get(token_id)
        if token is not None:
            self._by_id[token_id] = token.model_copy(update={"last_used_at": when})
