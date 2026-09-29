"""Boundary tests for app/infra/rest/approval_router.py.

The assertions here are the contract jira-mcp-portal was written against
(see its src/infra/atlassian/approvals.js and mockoon/atlassian-mcp.json):
camelCase throughout, both product keys always present, and no top-level
status of any kind -- the portal derives "partly approved" itself.
"""

from tests.support import app as test_app

_EXTERNAL_ID = "user@example.com"
_PAYLOAD = {
    "spaceKey": "FARM",
    "iao": "owner@defra.gov.uk",
    "reason": "need it",
    "userId": _EXTERNAL_ID,
    "products": ["jira", "confluence"],
}


def _headers() -> dict[str, str]:
    return {"X-User-Id": _EXTERNAL_ID}


def _jira_only() -> dict[str, object]:
    return {**_PAYLOAD, "products": ["jira"]}


class TestRequestingAccess:
    def test_creates_a_request_pending_for_every_product_asked_for(self):
        with test_app.rest_client() as (client, _overrides):
            response = client.post(
                "/approvals/spaces", json=_PAYLOAD, headers=_headers()
            )

            assert response.status_code == 201
            body = response.json()
            assert body["spaceKey"] == "FARM"
            assert body["iao"] == "owner@defra.gov.uk"
            assert body["reason"] == "need it"
            assert body["products"]["jira"] == {
                "requested": True,
                "status": "pending",
                "reviewerId": None,
                "decisionReason": None,
                "decidedAt": None,
            }
            assert body["products"]["confluence"]["status"] == "pending"

    def test_records_products_not_asked_for_rather_than_omitting_them(self):
        """The portal renders a row per product and derives the overall
        status from all of them, so an un-ticked product has to come back as
        a real "not-requested" entry, not an absent key."""
        with test_app.rest_client() as (client, _overrides):
            response = client.post(
                "/approvals/spaces", json=_jira_only(), headers=_headers()
            )

            assert response.json()["products"]["confluence"] == {
                "requested": False,
                "status": "not-requested",
                "reviewerId": None,
                "decisionReason": None,
                "decidedAt": None,
            }

    def test_carries_no_overall_status_of_its_own(self):
        """A request has one status per product and none of its own -- the
        portal owns the "partly approved" derivation, and a top-level status
        here would be a second, competing definition of it."""
        with test_app.rest_client() as (client, _overrides):
            body = client.post(
                "/approvals/spaces", json=_PAYLOAD, headers=_headers()
            ).json()

            assert "status" not in body
            assert "approved" not in body

    def test_conflicts_when_every_product_asked_for_is_already_open(self):
        with test_app.rest_client() as (client, _overrides):
            client.post("/approvals/spaces", json=_PAYLOAD, headers=_headers())
            response = client.post(
                "/approvals/spaces", json=_PAYLOAD, headers=_headers()
            )

            assert response.status_code == 409

    def test_rejects_a_request_naming_no_product(self):
        with test_app.rest_client() as (client, _overrides):
            response = client.post(
                "/approvals/spaces",
                json={**_PAYLOAD, "products": []},
                headers=_headers(),
            )

            assert response.status_code == 422

    def test_is_rejected_without_a_trusted_header(self):
        with test_app.rest_client() as (client, _overrides):
            response = client.post("/approvals/spaces", json=_PAYLOAD)

            assert response.status_code == 400

    def test_ignores_the_user_id_in_the_body(self):
        """The portal sends userId alongside the header for convenience. The
        header is the credential; trusting the body would let any caller
        file a request as anyone."""
        with test_app.rest_client() as (client, _overrides):
            client.post(
                "/approvals/spaces",
                json={**_PAYLOAD, "userId": "someone.else@example.com"},
                headers=_headers(),
            )

            mine = client.get("/approvals/spaces/FARM", headers=_headers())

            assert mine.status_code == 200


class TestAddingAProductLater:
    def test_amends_the_existing_request_rather_than_opening_a_second(self):
        """One document per (user, space) is what lets the portal show Jira
        approved and Confluence pending as a single row. Two documents would
        make the overall status ambiguous."""
        with test_app.rest_client() as (client, _overrides):
            first = client.post(
                "/approvals/spaces", json=_jira_only(), headers=_headers()
            ).json()

            second = client.post(
                "/approvals/spaces",
                json={**_PAYLOAD, "products": ["confluence"]},
                headers=_headers(),
            )

            assert second.status_code == 201
            body = second.json()
            assert body["id"] == first["id"]
            assert body["products"]["jira"]["status"] == "pending"
            assert body["products"]["confluence"]["status"] == "pending"


class TestGettingARequest:
    def test_returns_a_requested_space(self):
        with test_app.rest_client() as (client, _overrides):
            client.post("/approvals/spaces", json=_PAYLOAD, headers=_headers())

            response = client.get("/approvals/spaces/FARM", headers=_headers())

            assert response.status_code == 200
            assert response.json()["spaceKey"] == "FARM"

    def test_is_not_found_when_never_requested(self):
        with test_app.rest_client() as (client, _overrides):
            response = client.get("/approvals/spaces/NOSUCH", headers=_headers())

            assert response.status_code == 404

    def test_is_scoped_to_the_requesting_user(self):
        with test_app.rest_client() as (client, _overrides):
            client.post(
                "/approvals/spaces",
                json=_PAYLOAD,
                headers={"X-User-Id": "someone.else@example.com"},
            )

            response = client.get("/approvals/spaces/FARM", headers=_headers())

            assert response.status_code == 404
