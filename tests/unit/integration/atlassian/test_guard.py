import datetime as dt

import pytest

from app.integration.atlassian import approved_requests_source, models
from app.integration.atlassian import guard as guard_module
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
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )


def _static(jira: str = "", confluence: str = "") -> guard_module.AccessPolicy:
    source = guard_module.StaticAllowlistSource.from_csv(jira, confluence)
    return guard_module.AllowlistAccessPolicy(source)


@pytest.fixture
def store():
    return in_memory_space_access_request_store.InMemorySpaceAccessRequestStore()


def _approvals(store, user_id: str = "usr_a") -> guard_module.AccessPolicy:
    source = approved_requests_source.ApprovedRequestsAllowlistSource(user_id, store)
    return guard_module.AllowlistAccessPolicy(source)


class TestStaticAllowlistParsing:
    def test_strips_whitespace_and_drops_empty_entries(self):
        source = guard_module.StaticAllowlistSource.from_csv(
            "FARM, DEVOPS,", "  SPACE1 ,,SPACE2"
        )

        assert source.jira_projects == frozenset({"FARM", "DEVOPS"})
        assert source.confluence_spaces == frozenset({"SPACE1", "SPACE2"})

    def test_empty_strings_are_empty(self):
        source = guard_module.StaticAllowlistSource.from_csv("", "")

        assert source.jira_projects == frozenset()
        assert source.confluence_spaces == frozenset()

    @pytest.mark.parametrize("jira", ["*", "FARM,*", "farm", "F", "FARM-1", "FA RM"])
    def test_rejects_a_wildcard_or_malformed_jira_key(self, jira):
        """A key that can never match is a typo, and is caught at startup
        rather than silently denying."""
        with pytest.raises(ValueError, match="RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS"):
            guard_module.StaticAllowlistSource.from_csv(jira, "")

    @pytest.mark.parametrize("confluence", ["*", "~5b1234", "ENG-1", "a.b"])
    def test_rejects_a_wildcard_personal_or_malformed_space_key(self, confluence):
        with pytest.raises(
            ValueError, match="RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES"
        ):
            guard_module.StaticAllowlistSource.from_csv("", confluence)

    def test_accepts_mixed_case_confluence_keys(self):
        source = guard_module.StaticAllowlistSource.from_csv("", "Eng2")

        assert source.confluence_spaces == frozenset({"Eng2"})

    def test_warns_when_the_jira_var_has_no_entries(
        self, caplog: pytest.LogCaptureFixture
    ):
        with caplog.at_level("WARNING"):
            guard_module.StaticAllowlistSource.from_csv("", "SPACE1")

        assert "RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS" in caplog.text
        assert "RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES" not in caplog.text

    def test_warns_when_the_confluence_var_has_no_entries(
        self, caplog: pytest.LogCaptureFixture
    ):
        with caplog.at_level("WARNING"):
            guard_module.StaticAllowlistSource.from_csv("FARM", "")

        assert "RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES" in caplog.text
        assert "RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS" not in caplog.text

    def test_does_not_warn_when_both_have_entries(
        self, caplog: pytest.LogCaptureFixture
    ):
        with caplog.at_level("WARNING"):
            guard_module.StaticAllowlistSource.from_csv("FARM", "SPACE1")

        assert caplog.text == ""


class TestStaticAllowlistPolicy:
    async def test_permits_a_listed_jira_project(self):
        assert await _static(jira="FARM").check(JIRA, "FARM") is None

    async def test_denies_the_same_key_for_the_other_product(self):
        """A key listed for Jira grants nothing in Confluence."""
        with pytest.raises(guard_module.ForbiddenResourceError):
            await _static(jira="FARM").check(CONFLUENCE, "FARM")

    async def test_denies_an_unlisted_key(self):
        with pytest.raises(guard_module.ForbiddenResourceError):
            await _static(jira="FARM", confluence="FARM").check(JIRA, "OTHER")

    async def test_denies_everything_when_both_lists_are_empty(self):
        with pytest.raises(guard_module.ForbiddenResourceError):
            await _static().check(JIRA, "FARM")

    async def test_is_case_sensitive(self):
        with pytest.raises(guard_module.ForbiddenResourceError):
            await _static(jira="FARM").check(JIRA, "farm")

    async def test_the_message_names_the_key_and_product(self):
        with pytest.raises(guard_module.ForbiddenResourceError) as exc_info:
            await _static().check(CONFLUENCE, "FARM")

        assert "FARM" in str(exc_info.value)
        assert "confluence" in str(exc_info.value)


class TestApprovedRequestsPolicy:
    async def test_permits_an_approved_product(self, store):
        await store.create(_request("FARM", jira=models.ProductStatus.APPROVED))

        assert await _approvals(store).check(JIRA, "FARM") is None

    async def test_denies_a_product_approved_for_the_other_one(self, store):
        """The whole point of per-product approval -- reading Jira grants
        nothing in Confluence for the same space."""
        await store.create(_request("FARM", jira=models.ProductStatus.APPROVED))

        with pytest.raises(guard_module.ForbiddenResourceError):
            await _approvals(store).check(CONFLUENCE, "FARM")

    async def test_denies_a_pending_request(self, store):
        await store.create(_request("FARM", jira=models.ProductStatus.PENDING))

        with pytest.raises(guard_module.ForbiddenResourceError):
            await _approvals(store).check(JIRA, "FARM")

    async def test_denies_a_space_never_requested(self, store):
        with pytest.raises(guard_module.ForbiddenResourceError):
            await _approvals(store).check(JIRA, "FARM")

    async def test_denies_another_users_approval(self, store):
        """The source is bound to one user at construction; another user's
        approval does not count."""
        await store.create(_request("FARM", jira=models.ProductStatus.APPROVED))

        with pytest.raises(guard_module.ForbiddenResourceError):
            await _approvals(store, "usr_someone_else").check(JIRA, "FARM")

    async def test_the_message_says_how_to_get_access(self, store):
        """It reaches an LLM as a ToolError, so it has to say what to ask
        for rather than just "forbidden"."""
        with pytest.raises(guard_module.ForbiddenResourceError) as exc_info:
            await _approvals(store).check(CONFLUENCE, "FARM")

        message = str(exc_info.value)
        assert "FARM" in message
        assert "confluence" in message
        assert "Request access" in message


def test_the_old_exception_name_is_the_same_class():
    assert guard_module.ForbiddenSpaceError is guard_module.ForbiddenResourceError
