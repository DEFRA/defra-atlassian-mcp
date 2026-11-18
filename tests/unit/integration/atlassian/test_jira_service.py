import httpx2
import pytest

from app.integration.atlassian import client as client_module
from app.integration.atlassian import errors, models
from app.integration.atlassian import guard as guard_module
from app.integration.atlassian.jira import service as jira_module
from app.integration.linking import oauth_auth
from tests.fakes import fake_oauth_client, httpx_helpers
from tests.fixtures import atlassian as vendor

_ISSUE = vendor.issue()
_NO_ISSUES = httpx2.Response(200, json=vendor.search_results())


class _DenyingPolicy:
    """Records what it was asked, and always says no -- so a service that
    called the vendor before the policy would fail on an unconsumed
    response."""

    def __init__(self) -> None:
        self.asked: list[tuple[models.Product, str]] = []

    async def check(self, product: models.Product, key: str) -> None:
        self.asked.append((product, key))
        msg = "denied"
        raise guard_module.ForbiddenResourceError(msg)


class _PermittingPolicy:
    """Test-only: says yes to everything, so these tests cover what the
    service sends and renders. Policy behaviour is tested in test_guard.py,
    and the shipped code has no allow-everything policy."""

    async def check(
        self,
        product: models.Product,  # noqa: ARG002
        key: str,  # noqa: ARG002
    ) -> None:
        return None


def _make_service(responses, policy=None):
    http, transport = httpx_helpers.make_mock_client(responses)
    auth = oauth_auth.OAuthAtlassianAuth(
        "usr_a",
        fake_oauth_client.FakeOAuthClient("tok"),
        "https://api.atlassian.com",
    )
    client = client_module.AtlassianClient(http=http, auth=auth)
    policy = policy or _PermittingPolicy()
    return jira_module.JiraService(client=client, policy=policy), transport


class TestSearchIssues:
    async def test_addresses_the_users_cloud_site(self):
        service, transport = _make_service([_NO_ISSUES])

        await service.search_issues("FARM")

        url = str(transport.requests[0].url)
        assert url.startswith(
            "https://api.atlassian.com/ex/jira/test-cloud-id/rest/api/3/search/jql"
        )

    async def test_scopes_the_jql_to_the_project(self):
        service, transport = _make_service([_NO_ISSUES])

        await service.search_issues("FARM")

        jql = transport.requests[0].url.params["jql"]
        assert jql == 'project = "FARM" ORDER BY updated DESC'

    async def test_adds_text_and_status_filters(self):
        service, transport = _make_service([_NO_ISSUES])

        await service.search_issues("FARM", text="gate", status="Done")

        jql = transport.requests[0].url.params["jql"]
        assert 'text ~ "gate"' in jql
        assert 'status = "Done"' in jql

    async def test_escapes_quotes_so_a_value_cannot_add_its_own_clause(self):
        """The project key and text come from an LLM. A bare quote would
        close the literal and let the rest be read as JQL."""
        service, transport = _make_service([_NO_ISSUES])

        await service.search_issues('FARM" OR project = "SECRET')

        jql = transport.requests[0].url.params["jql"]
        assert jql == (
            'project = "FARM\\" OR project = \\"SECRET" ORDER BY updated DESC'
        )

    async def test_clamps_an_absurd_limit(self):
        service, transport = _make_service([_NO_ISSUES])

        await service.search_issues("FARM", limit=100000)

        assert transport.requests[0].url.params["maxResults"] == "100"

    async def test_renders_a_line_per_issue(self):
        service, _ = _make_service(
            [httpx2.Response(200, json=vendor.search_results(_ISSUE))]
        )

        result = await service.search_issues("FARM")

        assert result == "FARM-1 [Done] (Bug, Unassigned) Fix the gate"

    async def test_checks_the_policy_before_calling_the_vendor(self):
        policy = _DenyingPolicy()
        service, transport = _make_service([], policy=policy)

        with pytest.raises(guard_module.ForbiddenResourceError):
            await service.search_issues("FARM")

        assert policy.asked == [(models.Product.JIRA, "FARM")]
        assert transport.requests == []


class TestGetIssue:
    async def test_checks_the_project_the_key_belongs_to(self):
        """The project comes from the key's own prefix, which Jira
        guarantees, rather than from anything the caller asserts."""
        policy = _DenyingPolicy()
        service, _ = _make_service([], policy=policy)

        with pytest.raises(guard_module.ForbiddenResourceError):
            await service.get_issue("FARM-123")

        assert policy.asked == [(models.Product.JIRA, "FARM")]

    async def test_rejects_a_key_with_no_project_prefix(self):
        service, transport = _make_service([])

        with pytest.raises(jira_module.IssueNotFoundError):
            await service.get_issue("nonsense")

        assert transport.requests == []

    @pytest.mark.parametrize(
        "issue_key",
        [
            "FARM-1/../OTHER-5",
            "FARM-1/../../search",
            "FARM-1?fields=*all",
            "FARM-1#x",
            "FARM-1\n",
            "FARM-",
            "farm-1",
            "-1",
            "F-1",
        ],
    )
    async def test_refuses_anything_that_is_not_exactly_an_issue_key(self, issue_key):
        """The key is interpolated into the request path. FARM-1/../OTHER-5
        passed the allowlist check as FARM, and URL normalisation then fetched OTHER-5,
        so the key has to be rejected before the policy or the client."""
        policy = _DenyingPolicy()
        service, transport = _make_service([], policy=policy)

        with pytest.raises(jira_module.IssueNotFoundError):
            await service.get_issue(issue_key)

        assert policy.asked == []
        assert transport.requests == []

    async def test_accepts_underscores_and_digits_in_the_project(self):
        service, transport = _make_service(
            [httpx2.Response(200, json=vendor.issue("FARM_2-10"))]
        )

        result = await service.get_issue("FARM_2-10")

        assert "# FARM_2-10" in result
        assert (
            str(transport.requests[0].url)
            .split("?")[0]
            .endswith("/rest/api/3/issue/FARM_2-10")
        )

    async def test_asks_jira_for_the_project_field(self):
        service, transport = _make_service([httpx2.Response(200, json=_ISSUE)])

        await service.get_issue("FARM-1")

        fields = transport.requests[0].url.params["fields"].split(",")
        assert "project" in fields

    async def test_refuses_an_issue_that_has_moved_to_another_project(self):
        """Jira resolves the old key of a moved issue to the issue in its new
        project, so FARM-1 can come back as OTHER-9. The policy only checked
        FARM, so the issue must not be returned."""
        moved = vendor.issue("OTHER-9")
        service, _ = _make_service([httpx2.Response(200, json=moved)])

        with pytest.raises(jira_module.IssueNotFoundError) as exc_info:
            await service.get_issue("FARM-1")

        assert "Fix the gate" not in str(exc_info.value)

    async def test_refuses_an_issue_with_no_project_in_the_response(self):
        """Fail closed: if the project cannot be confirmed, the issue is not
        returned."""
        issue = vendor.issue()
        del issue["fields"]["project"]
        service, _ = _make_service([httpx2.Response(200, json=issue)])

        with pytest.raises(jira_module.IssueNotFoundError):
            await service.get_issue("FARM-1")

    async def test_renders_the_issue_fields(self):
        service, _ = _make_service([httpx2.Response(200, json=_ISSUE)])

        result = await service.get_issue("FARM-1")

        assert "# FARM-1 Fix the gate" in result
        assert "Status: Done" in result


class TestErrorTranslation:
    async def test_a_non_2xx_becomes_an_api_error(self):
        service, _ = _make_service([httpx2.Response(403)])

        with pytest.raises(errors.AtlassianApiError) as exc_info:
            await service.search_issues("FARM")

        assert exc_info.value.status_code == 403

    async def test_a_transport_failure_becomes_an_unavailable_error(self):
        service, _ = _make_service([httpx2.ConnectError("nope")])

        with pytest.raises(errors.AtlassianUnavailableError):
            await service.search_issues("FARM")
