from app.integration.linking import models as schemas
from app.integration.linking import ports as token_store


class InMemoryTokenStore(token_store.TokenStore):
    def __init__(
        self, initial: dict[str, schemas.AtlassianToken] | None = None
    ) -> None:
        self._store: dict[str, schemas.AtlassianToken] = dict(initial or {})

    async def store_tokens(self, user_id: str, token: schemas.AtlassianToken) -> None:
        self._store[user_id] = token

    async def get_tokens(self, user_id: str) -> schemas.AtlassianToken | None:
        return self._store.get(user_id)

    async def delete_tokens(self, user_id: str) -> None:
        self._store.pop(user_id, None)
