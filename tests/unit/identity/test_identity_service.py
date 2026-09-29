import pytest

from app.identity import service as identity_service
from tests.fakes import in_memory_identity_store


@pytest.fixture
def users() -> in_memory_identity_store.InMemoryUserStore:
    return in_memory_identity_store.InMemoryUserStore()


@pytest.fixture
def service(
    users: in_memory_identity_store.InMemoryUserStore,
) -> identity_service.IdentityService:
    return identity_service.IdentityService(users)


class TestGetOrCreate:
    async def test_creates_a_new_user(
        self, service: identity_service.IdentityService
    ) -> None:
        user = await service.get_or_create("a@example.com")

        assert user.user_id == "a@example.com"
        assert user.email == "a@example.com"

    async def test_is_idempotent_per_user_id(
        self, service: identity_service.IdentityService
    ) -> None:
        first = await service.get_or_create("a@example.com")
        second = await service.get_or_create("a@example.com")

        assert first.user_id == second.user_id

    async def test_different_addresses_get_different_users(
        self, service: identity_service.IdentityService
    ) -> None:
        first = await service.get_or_create("a@example.com")
        second = await service.get_or_create("b@example.com")

        assert first.user_id != second.user_id


class TestGetByUserId:
    async def test_found(self, service: identity_service.IdentityService) -> None:
        created = await service.get_or_create("a@example.com")

        found = await service.get_by_user_id(created.user_id)

        assert found is not None
        assert found.user_id == created.user_id

    async def test_not_found(self, service: identity_service.IdentityService) -> None:
        assert await service.get_by_user_id("does-not-exist@example.com") is None
