"""Transport-level auth for /mcp (app/entrypoints/http.py + app/infra/mcp/auth.py).

The in-memory fastmcp.Client used by test_tool_registry.py and
test_atlassian_tools.py bypasses transport auth entirely -- its FastMCPTransport
cannot carry a bearer token at all. So these tests go through a real ASGI
request instead, which is the only way to prove /mcp requires and verifies
one.
"""

import httpx2

from app.entrypoints import http as entrypoint
from app.identity import service as identity_service
from tests.support import app as test_app

_LIST_TOOLS_REQUEST = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
_MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _build_app_and_overrides():
    cfg = test_app.real_config()
    container, overrides = test_app._build_container(
        cfg=cfg,
        responses=[],
        tokens=None,
        states=None,
        access_requests=None,
        users=None,
        pats=None,
    )
    return entrypoint.create_app(cfg, container=container), overrides, cfg


async def _post_to_mcp(app, headers: dict[str, str]) -> httpx2.Response:
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        return await client.post("/mcp/", json=_LIST_TOOLS_REQUEST, headers=headers)


def _assert_rejected(response: httpx2.Response) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith(
        'Bearer error="invalid_token"'
    )


class TestRejectsInvalidTokens:
    async def test_an_unauthenticated_request(self):
        app, _overrides, _cfg = _build_app_and_overrides()

        response = await _post_to_mcp(app, _MCP_HEADERS)

        # RFC 6750 §3.1: the error attribute SHOULD NOT be included when no
        # credentials were presented at all (only an invalid/expired token
        # gets the full `error="invalid_token"` challenge asserted below).
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    async def test_a_token_that_was_never_minted(self):
        app, _overrides, _cfg = _build_app_and_overrides()

        response = await _post_to_mcp(
            app, {**_MCP_HEADERS, "Authorization": "Bearer mmcp_not-a-real-token"}
        )

        _assert_rejected(response)

    async def test_a_revoked_token(self):
        app, overrides, cfg = _build_app_and_overrides()
        identity_svc = identity_service.IdentityService(overrides.users)
        user = await identity_svc.get_or_create("u@example.com")
        ic = cfg.identity_config
        token_svc = identity_service.PersonalTokenService(
            overrides.pats,
            default_ttl_days=ic.default_ttl_days,
            max_ttl_days=ic.max_ttl_days,
            last_used_throttle_seconds=ic.last_used_throttle_seconds,
        )
        record, secret = await token_svc.mint(user.user_id, "test client")
        await token_svc.revoke(user.user_id, record.id)

        response = await _post_to_mcp(
            app, {**_MCP_HEADERS, "Authorization": f"Bearer {secret}"}
        )

        _assert_rejected(response)


class TestAcceptsAValidToken:
    async def test_the_call_runs_as_that_principal(self):
        """Full protocol round trip (session init + tools/list) rather than
        a raw one-shot POST -- StreamableHTTP requires a session id for
        anything past the first call, and fastmcp.Client already handles
        that handshake correctly. What this proves beyond
        test_atlassian_tools.py's happy paths is that the same bearer token
        that would 401 if wrong or revoked is actually what authorizes the
        call.
        """
        async with test_app.mcp_client(atlassian_token="atlassian-tok") as (
            client,
            _overrides,
            user_id,
        ):
            tools = await client.list_tools()

            assert {t.name for t in tools} == {
                "list_spaces",
                "search_jira_issues",
                "get_jira_issue",
                "list_confluence_pages",
                "get_confluence_page",
            }
            assert user_id == "mcp-test-user@example.com"
