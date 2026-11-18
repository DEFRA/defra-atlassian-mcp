import dishka
from pymongo.asynchronous import database

from app.config import http as http_config
from app.integration.atlassian import access_request_service
from app.integration.atlassian import guard as guard_module
from app.integration.atlassian import mongo_store as approval_mongo_store
from app.integration.atlassian import ports as approval_ports
from app.integration.linking import mongo_store
from app.integration.linking import ports as token_store

_TOKEN_COLLECTION = "atlassian_tokens"  # noqa: S105
_OAUTH_STATE_COLLECTION = "oauth_states"
_ACCESS_REQUEST_COLLECTION = "space_approvals"


class AtlassianProvider(dishka.Provider):
    @dishka.provide(scope=dishka.Scope.APP)
    def provide_token_store(
        self,
        db: database.AsyncDatabase,  # type: ignore[type-arg]
    ) -> token_store.TokenStore:
        return mongo_store.MongoTokenStore(db[_TOKEN_COLLECTION])

    @dishka.provide(scope=dishka.Scope.APP)
    async def provide_oauth_state_store(
        self,
        db: database.AsyncDatabase,  # type: ignore[type-arg]
    ) -> token_store.OAuthStateStore:
        store = mongo_store.MongoOAuthStateStore(db[_OAUTH_STATE_COLLECTION])
        await store.ensure_indexes()
        return store

    @dishka.provide(scope=dishka.Scope.APP)
    async def provide_space_access_request_store(
        self,
        db: database.AsyncDatabase,  # type: ignore[type-arg]
    ) -> approval_ports.SpaceAccessRequestStore:
        store = approval_mongo_store.MongoSpaceAccessRequestStore(
            db[_ACCESS_REQUEST_COLLECTION]
        )
        await store.ensure_indexes()
        return store

    @dishka.provide(scope=dishka.Scope.APP)
    def provide_access_request_service(
        self, store: approval_ports.SpaceAccessRequestStore
    ) -> access_request_service.SpaceAccessRequestService:
        return access_request_service.SpaceAccessRequestService(store)

    @dishka.provide(scope=dishka.Scope.APP)
    def provide_static_allowlist(
        self, config: http_config.HttpSettings
    ) -> guard_module.StaticAllowlistSource:
        """Built in both RESOURCE_GUARD_MODEs: the admin endpoint reports it
        either way, and in config_list mode it is what is enforced."""
        source = guard_module.StaticAllowlistSource(
            config.resource_guard_allowed_jira_projects,
            config.resource_guard_allowed_confluence_spaces,
        )
        guard_module.warn_if_empty(source)
        return source
