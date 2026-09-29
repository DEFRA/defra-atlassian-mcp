import datetime

from pymongo import ReturnDocument
from pymongo.asynchronous import collection

from app.identity import models, ports


class MongoUserStore(ports.UserStore):
    def __init__(self, users: collection.AsyncCollection) -> None:  # type: ignore[type-arg]
        self._collection = users

    async def ensure_indexes(self) -> None:
        """user_id is the email address itself, so this is the constraint
        that actually stops two identities colliding -- get_or_create's
        upsert relies on it to fail atomically rather than racing a
        get-then-insert."""
        await self._collection.create_index("user_id", unique=True)

    async def get_by_user_id(self, user_id: str) -> models.User | None:
        doc = await self._collection.find_one({"user_id": user_id}, {"_id": 0})
        if doc is None:
            return None
        return models.User.model_validate(doc)

    async def get_or_create(self, user_id: str) -> models.User:
        doc = await self._collection.find_one_and_update(
            {"user_id": user_id},
            {
                "$setOnInsert": {
                    "user_id": user_id,
                    "email": user_id,
                    "created_at": datetime.datetime.now(datetime.UTC),
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        return models.User.model_validate(doc)


class MongoPersonalAccessTokenStore(ports.PersonalAccessTokenStore):
    def __init__(self, tokens: collection.AsyncCollection) -> None:  # type: ignore[type-arg]
        self._collection = tokens

    async def create(self, token: models.PersonalAccessToken) -> None:
        await self._collection.replace_one(
            {"id": token.id}, token.model_dump(), upsert=True
        )

    async def get_by_hash(self, token_hash: str) -> models.PersonalAccessToken | None:
        doc = await self._collection.find_one({"token_hash": token_hash}, {"_id": 0})
        if doc is None:
            return None
        return models.PersonalAccessToken.model_validate(doc)

    async def get(self, token_id: str) -> models.PersonalAccessToken | None:
        doc = await self._collection.find_one({"id": token_id}, {"_id": 0})
        if doc is None:
            return None
        return models.PersonalAccessToken.model_validate(doc)

    async def list_for_user(self, user_id: str) -> list[models.PersonalAccessToken]:
        cursor = self._collection.find({"user_id": user_id}, {"_id": 0})
        return [models.PersonalAccessToken.model_validate(doc) async for doc in cursor]

    async def revoke(self, token_id: str) -> None:
        await self._collection.update_one(
            {"id": token_id},
            {"$set": {"revoked_at": datetime.datetime.now(datetime.UTC)}},
        )

    async def touch_last_used(self, token_id: str, when: datetime.datetime) -> None:
        await self._collection.update_one(
            {"id": token_id}, {"$set": {"last_used_at": when}}
        )
