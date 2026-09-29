import datetime

import pytest

from app.integration.atlassian import guard as guard_module
from app.integration.atlassian import models
from tests.fakes import in_memory_space_access_request_store

JIRA = models.Product.JIRA
CONFLUENCE = models.Product.CONFLUENCE


def _request(space_key: str, **statuses: models.ProductStatus):
    products = models.empty_products()
    for name, status in statuses.items():
        products[models.Product(name)] = models.ProductApproval(
            requested=True, status=status
        )
    return models.SpaceAccessRequest(
        id=f"req-{space_key}",
        user_id="usr_a",
        space_key=space_key,
        reason="need it",
        iao="owner@defra.gov.uk",
        products=products,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )


@pytest.fixture
def store():
    return in_memory_space_access_request_store.InMemorySpaceAccessRequestStore()


class TestAllowAllSpaceGuard:
    async def test_permits_anything(self):
        guard = guard_module.AllowAllSpaceGuard()

        assert await guard.check("usr_a", "FARM", JIRA) is None


class TestConfigAllowList:
    def test_from_csv_strips_whitespace_and_drops_empty_entries(self):
        allow_list = guard_module.ConfigAllowList.from_csv(
            "FARM, DEVOPS,", "  SPACE1 ,,SPACE2"
        )

        assert allow_list.jira_projects == frozenset({"FARM", "DEVOPS"})
        assert allow_list.confluence_spaces == frozenset({"SPACE1", "SPACE2"})

    def test_from_csv_on_empty_strings_is_empty(self):
        allow_list = guard_module.ConfigAllowList.from_csv("", "")

        assert allow_list.jira_projects == frozenset()
        assert allow_list.confluence_spaces == frozenset()

    def test_warns_when_the_jira_var_has_no_entries(
        self, caplog: pytest.LogCaptureFixture
    ):
        with caplog.at_level("WARNING"):
            guard_module.ConfigAllowList.from_csv("", "SPACE1")

        assert "RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS" in caplog.text
        assert "RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES" not in caplog.text

    def test_warns_when_the_confluence_var_has_no_entries(
        self, caplog: pytest.LogCaptureFixture
    ):
        with caplog.at_level("WARNING"):
            guard_module.ConfigAllowList.from_csv("FARM", "")

        assert "RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES" in caplog.text
        assert "RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS" not in caplog.text

    def test_does_not_warn_when_both_have_entries(
        self, caplog: pytest.LogCaptureFixture
    ):
        with caplog.at_level("WARNING"):
            guard_module.ConfigAllowList.from_csv("FARM", "SPACE1")

        assert caplog.text == ""


class TestConfigAllowListSpaceGuard:
    async def test_permits_a_listed_jira_project(self):
        allow_list = guard_module.ConfigAllowList.from_csv("FARM", "")
        guard = guard_module.ConfigAllowListSpaceGuard(allow_list)

        assert await guard.check("usr_a", "FARM", JIRA) is None

    async def test_denies_the_same_key_for_the_other_product(self):
        """A key listed for Jira grants nothing in Confluence -- same
        per-product principle as AllowListSpaceGuard."""
        allow_list = guard_module.ConfigAllowList.from_csv("FARM", "")
        guard = guard_module.ConfigAllowListSpaceGuard(allow_list)

        with pytest.raises(guard_module.ForbiddenSpaceError):
            await guard.check("usr_a", "FARM", CONFLUENCE)

    async def test_denies_an_unlisted_key(self):
        allow_list = guard_module.ConfigAllowList.from_csv("FARM", "FARM")
        guard = guard_module.ConfigAllowListSpaceGuard(allow_list)

        with pytest.raises(guard_module.ForbiddenSpaceError):
            await guard.check("usr_a", "OTHER", JIRA)

    async def test_denies_everything_when_both_lists_are_empty(self):
        allow_list = guard_module.ConfigAllowList.from_csv("", "")
        guard = guard_module.ConfigAllowListSpaceGuard(allow_list)

        with pytest.raises(guard_module.ForbiddenSpaceError):
            await guard.check("usr_a", "FARM", JIRA)

    async def test_is_case_sensitive(self):
        allow_list = guard_module.ConfigAllowList.from_csv("FARM", "")
        guard = guard_module.ConfigAllowListSpaceGuard(allow_list)

        with pytest.raises(guard_module.ForbiddenSpaceError):
            await guard.check("usr_a", "farm", JIRA)

    async def test_the_message_names_the_space_and_product(self):
        allow_list = guard_module.ConfigAllowList.from_csv("", "")
        guard = guard_module.ConfigAllowListSpaceGuard(allow_list)

        with pytest.raises(guard_module.ForbiddenSpaceError) as exc_info:
            await guard.check("usr_a", "FARM", CONFLUENCE)

        assert "FARM" in str(exc_info.value)
        assert "confluence" in str(exc_info.value)


class TestAllowListSpaceGuard:
    async def test_permits_an_approved_product(self, store):
        await store.create(_request("FARM", jira=models.ProductStatus.APPROVED))
        guard = guard_module.AllowListSpaceGuard(store)

        assert await guard.check("usr_a", "FARM", JIRA) is None

    async def test_denies_a_product_approved_for_the_other_one(self, store):
        """The whole point of per-product approval -- reading Jira grants
        nothing in Confluence for the same space."""
        await store.create(_request("FARM", jira=models.ProductStatus.APPROVED))
        guard = guard_module.AllowListSpaceGuard(store)

        with pytest.raises(guard_module.ForbiddenSpaceError):
            await guard.check("usr_a", "FARM", CONFLUENCE)

    async def test_denies_a_pending_request(self, store):
        await store.create(_request("FARM", jira=models.ProductStatus.PENDING))
        guard = guard_module.AllowListSpaceGuard(store)

        with pytest.raises(guard_module.ForbiddenSpaceError):
            await guard.check("usr_a", "FARM", JIRA)

    async def test_denies_a_space_never_requested(self, store):
        guard = guard_module.AllowListSpaceGuard(store)

        with pytest.raises(guard_module.ForbiddenSpaceError):
            await guard.check("usr_a", "FARM", JIRA)

    async def test_denies_another_users_approval(self, store):
        await store.create(_request("FARM", jira=models.ProductStatus.APPROVED))
        guard = guard_module.AllowListSpaceGuard(store)

        with pytest.raises(guard_module.ForbiddenSpaceError):
            await guard.check("usr_someone_else", "FARM", JIRA)

    async def test_the_message_names_the_space_and_product(self, store):
        """It reaches an LLM as a ToolError, so it has to say what to ask
        for rather than just "forbidden"."""
        guard = guard_module.AllowListSpaceGuard(store)

        with pytest.raises(guard_module.ForbiddenSpaceError) as exc_info:
            await guard.check("usr_a", "FARM", CONFLUENCE)

        assert "FARM" in str(exc_info.value)
        assert "confluence" in str(exc_info.value)
