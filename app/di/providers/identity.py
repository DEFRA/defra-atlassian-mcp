import dishka
from pymongo.asynchronous import database

from app import config as app_config
from app.identity import mongo_store, ports, service


class IdentityProvider(dishka.Provider):
    scope = dishka.Scope.APP

    @dishka.provide
    async def provide_user_store(
        self,
        db: database.AsyncDatabase,  # type: ignore[type-arg]
    ) -> ports.UserStore:
        store = mongo_store.MongoUserStore(db["users"])
        await store.ensure_indexes()
        return store

    @dishka.provide
    def provide_pat_store(
        self,
        db: database.AsyncDatabase,  # type: ignore[type-arg]
    ) -> ports.PersonalAccessTokenStore:
        return mongo_store.MongoPersonalAccessTokenStore(db["personal_access_tokens"])

    @dishka.provide
    def provide_identity_service(
        self, users: ports.UserStore
    ) -> service.IdentityService:
        return service.IdentityService(users)

    @dishka.provide
    def provide_personal_token_service(
        self,
        tokens: ports.PersonalAccessTokenStore,
        identity_config: app_config.IdentityConfig,
    ) -> service.PersonalTokenService:
        return service.PersonalTokenService(
            tokens,
            default_ttl_days=identity_config.default_ttl_days,
            max_ttl_days=identity_config.max_ttl_days,
            last_used_throttle_seconds=identity_config.last_used_throttle_seconds,
        )
