"""Boundary tests for app/infra/rest/admin_router.py.

The decision is per product, not per request: approving a space for both
Jira and Confluence is two calls, and each one must leave the other product
exactly as it was.
"""

from app.integration.atlassian import access_request_service as service_module
from app.integration.atlassian import models
from tests.support import app as test_app

_REVIEWER_USER_ID = "reviewer@example.com"

_APPROVAL = {
    "product": "jira",
    "decisionReason": "looks good",
    "dataHandlingFormRef": "DH-1",
    "riskAssessmentRef": "RA-1",
}


def _headers() -> dict[str, str]:
    return {"X-User-Id": _REVIEWER_USER_ID}


def _seed_request(client, overrides, *products: models.Product):
    """Seed through a real SpaceAccessRequestService bound to the app's own
    store, run on the TestClient's own loop (never a bare asyncio.run()) --
    the store is a plain dict fake today, but seeding off-loop would break
    silently the day it holds an asyncio.Lock."""
    service = service_module.SpaceAccessRequestService(overrides.access_requests)
    return test_app.seed(
        client,
        service.request_access,
        "usr_a",
        "FARM",
        "owner@x.com",
        "why",
        list(products or (models.Product.JIRA, models.Product.CONFLUENCE)),
    )


class TestListingPendingRequests:
    def test_lists_requests_with_a_product_still_pending(self):
        with test_app.rest_client() as (client, overrides):
            _seed_request(client, overrides)

            response = client.get("/admin/access-requests", headers=_headers())

            assert response.status_code == 200
            body = response.json()
            assert body[0]["spaceKey"] == "FARM"
            assert body[0]["userId"] == "usr_a"

    def test_tolerates_the_status_filter_the_portal_sends(self):
        """The portal sends ?status=pending even though this route only ever
        returns pending requests."""
        with test_app.rest_client() as (client, overrides):
            _seed_request(client, overrides)

            response = client.get(
                "/admin/access-requests",
                params={"status": "pending"},
                headers=_headers(),
            )

            assert response.status_code == 200
            assert len(response.json()) == 1

    def test_is_rejected_without_a_trusted_header(self):
        with test_app.rest_client() as (client, _overrides):
            assert client.get("/admin/access-requests").status_code == 400


class TestApprove:
    def test_records_the_decision_against_that_product_only(self):
        with test_app.rest_client() as (client, overrides):
            request = _seed_request(client, overrides)

            response = client.post(
                f"/admin/access-requests/{request.id}/approve",
                json=_APPROVAL,
                headers=_headers(),
            )

            assert response.status_code == 200
            body = response.json()
            assert body["products"]["jira"]["status"] == "approved"
            assert body["products"]["jira"]["reviewerId"] == _REVIEWER_USER_ID
            assert body["products"]["jira"]["decisionReason"] == "looks good"
            assert body["products"]["jira"]["decidedAt"] is not None
            assert body["dataHandlingFormRef"] == "DH-1"
            assert body["riskAssessmentRef"] == "RA-1"

    def test_leaves_the_other_product_untouched(self):
        """An IAO can approve a space for Jira and still be deciding about
        Confluence -- approving one must not silently decide the other."""
        with test_app.rest_client() as (client, overrides):
            request = _seed_request(client, overrides)

            body = client.post(
                f"/admin/access-requests/{request.id}/approve",
                json=_APPROVAL,
                headers=_headers(),
            ).json()

            assert body["products"]["confluence"] == {
                "requested": True,
                "status": "pending",
                "reviewerId": None,
                "decisionReason": None,
                "decidedAt": None,
            }

    def test_conflicts_when_that_product_is_already_decided(self):
        with test_app.rest_client() as (client, overrides):
            request = _seed_request(client, overrides)
            client.post(
                f"/admin/access-requests/{request.id}/approve",
                json=_APPROVAL,
                headers=_headers(),
            )

            second = client.post(
                f"/admin/access-requests/{request.id}/approve",
                json=_APPROVAL,
                headers=_headers(),
            )

            assert second.status_code == 409

    def test_conflicts_for_a_product_that_was_never_requested(self):
        with test_app.rest_client() as (client, overrides):
            request = _seed_request(client, overrides, models.Product.JIRA)

            response = client.post(
                f"/admin/access-requests/{request.id}/approve",
                json={**_APPROVAL, "product": "confluence"},
                headers=_headers(),
            )

            assert response.status_code == 409

    def test_is_not_found_for_an_unknown_request(self):
        with test_app.rest_client() as (client, _overrides):
            response = client.post(
                "/admin/access-requests/nope/approve",
                json=_APPROVAL,
                headers=_headers(),
            )

            assert response.status_code == 404


class TestReject:
    def test_records_the_rejection_against_that_product_only(self):
        with test_app.rest_client() as (client, overrides):
            request = _seed_request(client, overrides)

            body = client.post(
                f"/admin/access-requests/{request.id}/reject",
                json={"product": "confluence", "decisionReason": "not justified"},
                headers=_headers(),
            ).json()

            assert body["products"]["confluence"]["status"] == "rejected"
            assert body["products"]["confluence"]["decisionReason"] == "not justified"
            assert body["products"]["jira"]["status"] == "pending"

    def test_is_not_found_for_an_unknown_request(self):
        with test_app.rest_client() as (client, _overrides):
            response = client.post(
                "/admin/access-requests/nope/reject",
                json={"product": "jira", "decisionReason": "no"},
                headers=_headers(),
            )

            assert response.status_code == 404


class TestDecidingOneProductThenTheOther:
    def test_leaves_the_request_off_the_pending_list_once_nothing_is_pending(self):
        with test_app.rest_client() as (client, overrides):
            request = _seed_request(client, overrides)
            client.post(
                f"/admin/access-requests/{request.id}/approve",
                json=_APPROVAL,
                headers=_headers(),
            )
            client.post(
                f"/admin/access-requests/{request.id}/reject",
                json={"product": "confluence", "decisionReason": "no"},
                headers=_headers(),
            )

            pending = client.get("/admin/access-requests", headers=_headers()).json()

            assert pending == []
