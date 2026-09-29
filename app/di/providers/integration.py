import dishka
from pymongo.asynchronous import database

from app import config as app_config
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
    def provide_config_allow_list(
        self, config: app_config.AppConfig
    ) -> guard_module.ConfigAllowList:
        return guard_module.ConfigAllowList.from_csv(
            config.resource_guard_allowed_jira_projects,
            config.resource_guard_allowed_confluence_spaces,
        )

    @dishka.provide(scope=dishka.Scope.APP)
    def provide_space_guard(
        self,
        config: app_config.AppConfig,
        store: approval_ports.SpaceAccessRequestStore,
        allow_list: guard_module.ConfigAllowList,
    ) -> guard_module.SpaceGuard:
        """The one line an operator changes to turn enforcement on (see
        RESOURCE_GUARD_MODE): "config_list" (default) checks the hand-managed
        CSV allow list, "allow_list" binds AllowListSpaceGuard once the admin
        review workflow has real approvals to check against."""
        if config.resource_guard_mode == "allow_list":
            return guard_module.AllowListSpaceGuard(store)
        if config.resource_guard_mode == "config_list":
            return guard_module.ConfigAllowListSpaceGuard(allow_list)
        return guard_module.AllowAllSpaceGuard()
