import datetime
import uuid
from collections.abc import Callable

from pymongo.asynchronous import collection

from app.integration.linking import exceptions, models, pkce, ports


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class MongoTokenStore(ports.TokenStore):
    def __init__(self, atlassian_collection: collection.AsyncCollection) -> None:  # type: ignore[type-arg]
        self._collection = atlassian_collection

    async def store_tokens(self, user_id: str, token: models.AtlassianToken) -> None:
        doc = {"user_id": user_id, **token.model_dump()}

        await self._collection.replace_one({"user_id": user_id}, doc, upsert=True)

    async def get_tokens(self, user_id: str) -> models.AtlassianToken | None:
        doc = await self._collection.find_one({"user_id": user_id}, {"_id": 0})

        if doc is None:
            return None

        return models.AtlassianToken.model_validate(doc)

    async def delete_tokens(self, user_id: str) -> None:
        await self._collection.delete_one({"user_id": user_id})


class MongoOAuthStateStore(ports.OAuthStateStore):
    """Mongo-backed OAuth state store. A TTL index on ``expires_at`` sweeps
    stale entries in the background, so this works correctly across multiple
    worker processes -- unlike the process-local in-memory version it
    replaces.
    """

    def __init__(
        self,
        states: collection.AsyncCollection,  # type: ignore[type-arg]
        clock: Callable[[], datetime.datetime] = _utc_now,
        ttl: datetime.timedelta = datetime.timedelta(minutes=10),
    ) -> None:
        self._collection = states
        self._clock = clock
        self._ttl = ttl

    async def ensure_indexes(self) -> None:
        await self._collection.create_index("expires_at", expireAfterSeconds=0)

    async def issue(self, user_id: str) -> models.IssuedState:
        state = str(uuid.uuid4())
        code_verifier = pkce.generate_code_verifier()

        await self._collection.insert_one(
            {
                "_id": state,
                "user_id": user_id,
                "code_verifier": code_verifier,
                "expires_at": self._clock() + self._ttl,
            }
        )

        return models.IssuedState(
            state=state, code_challenge=pkce.derive_code_challenge(code_verifier)
        )

    async def consume(self, state: str) -> models.OAuthState:
        doc = await self._collection.find_one_and_delete({"_id": state})

        if doc is None:
            msg = "Invalid or unknown OAuth state"
            raise exceptions.OAuthStateError(msg)

        oauth_state = models.OAuthState(
            user_id=doc["user_id"],
            code_verifier=doc["code_verifier"],
            expires_at=doc["expires_at"],
        )

        if oauth_state.expires_at < self._clock():
            msg = "OAuth state has expired"
            raise exceptions.OAuthStateError(msg)

        return oauth_state
