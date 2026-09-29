"""Boundary tests for the config-driven resource guard read endpoint in
app/infra/rest/admin_router.py (GET /admin/resource-guard/allowed-spaces).

This mirrors the current, real values RESOURCE_GUARD_MODE and the two CSV
env vars would produce -- it exists so the portal can display the
hand-managed allow list to users, independent of the SpaceAccessRequest
workflow tested in test_admin_access_requests.py.
"""

from tests.support import app as test_app

_HEADERS = {"X-User-Id": "reviewer@example.com"}


class TestGetConfigAllowList:
    def test_reports_the_active_mode_and_both_lists(self):
        with test_app.rest_client(
            resource_guard_mode="config_list",
            resource_guard_allowed_jira_projects="FARM, DEVOPS",
            resource_guard_allowed_confluence_spaces="FARM",
        ) as (client, _overrides):
            response = client.get(
                "/admin/resource-guard/allowed-spaces", headers=_HEADERS
            )

            assert response.status_code == 200
            body = response.json()
            assert body["mode"] == "config_list"
            assert body["jiraProjects"] == ["DEVOPS", "FARM"]
            assert body["confluenceSpaces"] == ["FARM"]

    def test_reports_empty_lists_when_unconfigured(self):
        with test_app.rest_client(resource_guard_mode="config_list") as (
            client,
            _overrides,
        ):
            response = client.get(
                "/admin/resource-guard/allowed-spaces", headers=_HEADERS
            )

            assert response.status_code == 200
            body = response.json()
            assert body["jiraProjects"] == []
            assert body["confluenceSpaces"] == []

    def test_reports_the_mode_even_when_not_config_list(self):
        """The endpoint always reflects what's configured, so the portal can
        tell when this list isn't the one actually being enforced."""
        with test_app.rest_client(resource_guard_mode="allow_list") as (
            client,
            _overrides,
        ):
            response = client.get(
                "/admin/resource-guard/allowed-spaces", headers=_HEADERS
            )

            assert response.status_code == 200
            assert response.json()["mode"] == "allow_list"

    def test_is_rejected_without_a_trusted_header(self):
        with test_app.rest_client() as (client, _overrides):
            assert client.get("/admin/resource-guard/allowed-spaces").status_code == 400
