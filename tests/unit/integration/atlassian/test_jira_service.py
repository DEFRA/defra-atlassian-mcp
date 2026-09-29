import httpx2
import pytest

from app.integration.atlassian import client as client_module
from app.integration.atlassian import guard as guard_module
from app.integration.atlassian import models
from app.integration.atlassian.jira import service as jira_module
from app.integration.linking import exceptions
from tests.fakes import fake_oauth_client, httpx_helpers
from tests.fixtures import atlassian as vendor
from tests.support import app as test_app

_ISSUE = vendor.issue()
_NO_ISSUES = httpx2.Response(200, json=vendor.search_results())


class _DenyingGuard(guard_module.SpaceGuard):
    """Records what it was asked, and always says no -- so a service that
    called the vendor before the guard would fail on an unconsumed
    response."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str, models.Product]] = []

    async def check(
        self, user_id: str, space_key: str, product: models.Product
    ) -> None:
        self.asked.append((user_id, space_key, product))
        msg = "denied"
        raise guard_module.ForbiddenSpaceError(msg)


def _make_service(responses, guard=None):
    http, transport = httpx_helpers.make_mock_client(responses)
    client = client_module.AtlassianClient(
        config=test_app.real_config(),
        client=http,
        oauth=fake_oauth_client.FakeOAuthClient("tok"),  # type: ignore[arg-type]
    )
    guard = guard or guard_module.AllowAllSpaceGuard()
    return jira_module.JiraService(client=client, guard=guard), transport


class TestSearchIssues:
    async def test_addresses_the_users_cloud_site(self):
        service, transport = _make_service([_NO_ISSUES])

        await service.search_issues("usr_a", "FARM")

        url = str(transport.requests[0].url)
        assert url.startswith(
            "https://api.atlassian.com/ex/jira/test-cloud-id/rest/api/3/search/jql"
        )

    async def test_scopes_the_jql_to_the_project(self):
        service, transport = _make_service([_NO_ISSUES])

        await service.search_issues("usr_a", "FARM")

        jql = transport.requests[0].url.params["jql"]
        assert jql == 'project = "FARM" ORDER BY updated DESC'

    async def test_adds_text_and_status_filters(self):
        service, transport = _make_service([_NO_ISSUES])

        await service.search_issues("usr_a", "FARM", text="gate", status="Done")

        jql = transport.requests[0].url.params["jql"]
        assert 'text ~ "gate"' in jql
        assert 'status = "Done"' in jql

    async def test_escapes_quotes_so_a_value_cannot_add_its_own_clause(self):
        """The project key and text come from an LLM. A bare quote would
        close the literal and let the rest be read as JQL."""
        service, transport = _make_service([_NO_ISSUES])

        await service.search_issues("usr_a", 'FARM" OR project = "SECRET')

        jql = transport.requests[0].url.params["jql"]
        assert jql == (
            'project = "FARM\\" OR project = \\"SECRET" ORDER BY updated DESC'
        )

    async def test_clamps_an_absurd_limit(self):
        service, transport = _make_service([_NO_ISSUES])

        await service.search_issues("usr_a", "FARM", limit=100000)

        assert transport.requests[0].url.params["maxResults"] == "100"

    async def test_renders_a_line_per_issue(self):
        service, _ = _make_service(
            [httpx2.Response(200, json=vendor.search_results(_ISSUE))]
        )

        result = await service.search_issues("usr_a", "FARM")

        assert result == "FARM-1 [Done] (Bug, Unassigned) Fix the gate"

    async def test_checks_the_guard_before_calling_the_vendor(self):
        guard = _DenyingGuard()
        service, transport = _make_service([], guard=guard)

        with pytest.raises(guard_module.ForbiddenSpaceError):
            await service.search_issues("usr_a", "FARM")

        assert guard.asked == [("usr_a", "FARM", models.Product.JIRA)]
        assert transport.requests == []


class TestGetIssue:
    async def test_guards_on_the_project_the_key_belongs_to(self):
        """The project comes from the key's own prefix, which Jira
        guarantees, rather than from anything the caller asserts."""
        guard = _DenyingGuard()
        service, _ = _make_service([], guard=guard)

        with pytest.raises(guard_module.ForbiddenSpaceError):
            await service.get_issue("usr_a", "FARM-123")

        assert guard.asked == [("usr_a", "FARM", models.Product.JIRA)]

    async def test_rejects_a_key_with_no_project_prefix(self):
        service, transport = _make_service([])

        with pytest.raises(jira_module.IssueNotFoundError):
            await service.get_issue("usr_a", "nonsense")

        assert transport.requests == []

    async def test_renders_the_issue_fields(self):
        service, _ = _make_service([httpx2.Response(200, json=_ISSUE)])

        result = await service.get_issue("usr_a", "FARM-1")

        assert "# FARM-1 Fix the gate" in result
        assert "Status: Done" in result


class TestErrorTranslation:
    async def test_a_non_2xx_becomes_an_api_error(self):
        service, _ = _make_service([httpx2.Response(403)])

        with pytest.raises(exceptions.AtlassianApiError) as exc_info:
            await service.search_issues("usr_a", "FARM")

        assert exc_info.value.status_code == 403

    async def test_a_transport_failure_becomes_an_unavailable_error(self):
        service, _ = _make_service([httpx2.ConnectError("nope")])

        with pytest.raises(exceptions.AtlassianUnavailableError):
            await service.search_issues("usr_a", "FARM")
