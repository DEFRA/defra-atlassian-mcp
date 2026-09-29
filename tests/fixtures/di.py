import contextlib
from collections.abc import AsyncIterator

import dishka

from app.integration.atlassian import guard as guard_module
from app.integration.atlassian import ports as approval_ports
from app.integration.linking import ports as token_store
from tests.fakes import (
    in_memory_oauth_state_store,
    in_memory_space_access_request_store,
    in_memory_token_store,
)


class TestProvider(dishka.Provider):
    """APP-scoped provider that substitutes in-memory fakes for all persistence."""

    scope = dishka.Scope.APP

    @dishka.provide
    def provide_token_store(self) -> token_store.TokenStore:
        return in_memory_token_store.InMemoryTokenStore()

    @dishka.provide
    def provide_space_access_request_store(
        self,
    ) -> approval_ports.SpaceAccessRequestStore:
        return in_memory_space_access_request_store.InMemorySpaceAccessRequestStore()

    @dishka.provide
    def provide_space_guard(self) -> guard_module.SpaceGuard:
        return guard_module.AllowAllSpaceGuard()

    @dishka.provide
    def provide_state_store(self) -> token_store.OAuthStateStore:
        return in_memory_oauth_state_store.InMemoryOAuthStateStore()


@contextlib.asynccontextmanager
async def build_test_container() -> AsyncIterator[dishka.AsyncContainer]:
    async with dishka.make_async_container(TestProvider()) as container:
        yield container
