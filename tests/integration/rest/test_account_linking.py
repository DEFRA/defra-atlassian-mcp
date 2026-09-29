"""Boundary tests for the Atlassian OAuth callback
(app/infra/rest/linking_router.py).

Atlassian redirects the browser to the *portal*, which forwards the code
and state to this route, so the callback here always arrives with a trusted
X-User-Id header. The cross-user 403 is what
tests/unit/auth/test_cross_surface_identity.py's invariant exists to
protect.

Note that linking is two vendor calls, not one: the token exchange, then
/oauth/token/accessible-resources to resolve the cloud id. Every `responses`
list below reflects that.
"""

import httpx2

from tests.support import app as test_app

_EXTERNAL_ID = "user@example.com"
_TOKEN_RESPONSE = httpx2.Response(
    200,
    json={
        "access_token": "atlassian-access-token",
        "refresh_token": "atlassian-refresh-token",
        "expires_in": 3600,
    },
)
_SITES_RESPONSE = httpx2.Response(
    200, json=[{"id": "cloud-1", "name": "example", "url": "https://x.atlassian.net"}]
)
_LINK_RESPONSES = [_TOKEN_RESPONSE, _SITES_RESPONSE]


def _headers(user_id: str = _EXTERNAL_ID) -> dict[str, str]:
    return {"X-User-Id": user_id}


def _link(client, overrides, *, user_id: str = _EXTERNAL_ID) -> None:
    issued = test_app.seed(client, overrides.states.issue, user_id)
    client.get(
        "/linking/callback",
        params={"code": "auth-code", "state": issued.state},
        headers=_headers(user_id),
    )


class TestCallback:
    def test_completing_it_stores_tokens_for_the_issuing_user(self):
        with test_app.rest_client(responses=list(_LINK_RESPONSES)) as (
            client,
            overrides,
        ):
            issued = test_app.seed(client, overrides.states.issue, _EXTERNAL_ID)

            response = client.get(
                "/linking/callback",
                params={"code": "auth-code", "state": issued.state},
                headers=_headers(),
            )

            assert response.status_code == 200
            assert response.json() == {"status": "success"}
            stored = test_app.seed(client, overrides.tokens.get_tokens, _EXTERNAL_ID)
            assert stored is not None
            assert stored.access_token == "atlassian-access-token"

    def test_stores_the_resolved_cloud_id_alongside_the_token(self):
        """Without it, every later product call has no site to address."""
        with test_app.rest_client(responses=list(_LINK_RESPONSES)) as (
            client,
            overrides,
        ):
            _link(client, overrides)

            stored = test_app.seed(client, overrides.tokens.get_tokens, _EXTERNAL_ID)

            assert stored is not None
            assert stored.cloud_id == "cloud-1"

    def test_a_replayed_or_forged_state_is_rejected(self):
        with test_app.rest_client() as (client, _overrides):
            response = client.get(
                "/linking/callback",
                params={"code": "auth-code", "state": "not-a-real-state"},
                headers=_headers(),
            )

            assert response.status_code == 400

    def test_another_users_callback_is_forbidden(self):
        with test_app.rest_client() as (client, overrides):
            issued = test_app.seed(client, overrides.states.issue, "someone-else")

            response = client.get(
                "/linking/callback",
                params={"code": "auth-code", "state": issued.state},
                headers=_headers(),
            )

            assert response.status_code == 403
            assert (
                test_app.seed(client, overrides.tokens.get_tokens, _EXTERNAL_ID) is None
            )

    def test_an_account_with_no_accessible_site_is_a_bad_request(self):
        responses = [_TOKEN_RESPONSE, httpx2.Response(200, json=[])]
        with test_app.rest_client(responses=responses) as (client, overrides):
            issued = test_app.seed(client, overrides.states.issue, _EXTERNAL_ID)

            response = client.get(
                "/linking/callback",
                params={"code": "auth-code", "state": issued.state},
                headers=_headers(),
            )

            assert response.status_code == 400
            assert (
                test_app.seed(client, overrides.tokens.get_tokens, _EXTERNAL_ID) is None
            )


class TestStatus:
    def test_reports_not_linked_before_connecting(self):
        with test_app.rest_client() as (client, _overrides):
            response = client.get("/linking/status", headers=_headers())

            assert response.status_code == 200
            assert response.json() == {"linked": False, "accessTokenExpiresAt": None}

    def test_reports_linked_after_connecting(self):
        with test_app.rest_client(responses=list(_LINK_RESPONSES)) as (
            client,
            overrides,
        ):
            _link(client, overrides)

            response = client.get("/linking/status", headers=_headers())

            data = response.json()
            assert data["linked"] is True
            assert data["accessTokenExpiresAt"] is not None


class TestTestConnection:
    def test_returns_401_if_not_linked(self):
        with test_app.rest_client() as (client, _overrides):
            response = client.get("/linking/test-connection", headers=_headers())

            assert response.status_code == 401
            assert (
                "no valid atlassian access token" in response.json()["detail"].lower()
            )

    def test_returns_the_linked_profile_when_atlassian_accepts_the_token(self):
        """The portal renders the identity from `profile`, preferring
        displayName -- a bare {"status": "success"} leaves it blank."""
        responses = [
            *_LINK_RESPONSES,
            httpx2.Response(
                200,
                json={
                    "account_id": "acc-1",
                    "name": "Dev User",
                    "email": "dev@example.com",
                },
            ),
        ]
        with test_app.rest_client(responses=responses) as (client, overrides):
            _link(client, overrides)

            response = client.get("/linking/test-connection", headers=_headers())

            assert response.status_code == 200
            assert response.json() == {
                "status": "success",
                "profile": {
                    "accountId": "acc-1",
                    "displayName": "Dev User",
                    "email": "dev@example.com",
                },
            }

    def test_returns_401_if_atlassian_rejects_the_token(self):
        responses = [*_LINK_RESPONSES, httpx2.Response(401)]
        with test_app.rest_client(responses=responses) as (client, overrides):
            _link(client, overrides)

            response = client.get("/linking/test-connection", headers=_headers())

            assert response.status_code == 401
            assert "rejected the access token" in response.json()["detail"]

    def test_returns_502_on_an_atlassian_server_error(self):
        responses = [*_LINK_RESPONSES, httpx2.Response(500)]
        with test_app.rest_client(responses=responses) as (client, overrides):
            _link(client, overrides)

            response = client.get("/linking/test-connection", headers=_headers())

            assert response.status_code == 502
            assert "status" in response.json()["detail"].lower()

    def test_returns_502_if_atlassian_is_unreachable(self):
        responses = [*_LINK_RESPONSES, httpx2.ConnectError("Connection refused")]
        with test_app.rest_client(responses=responses) as (client, overrides):
            _link(client, overrides)

            response = client.get("/linking/test-connection", headers=_headers())

            assert response.status_code == 502
            assert response.json() == {"detail": "Atlassian is unreachable"}
