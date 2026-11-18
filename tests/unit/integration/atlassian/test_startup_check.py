import httpx2
import pytest

from app.integration.atlassian import client as client_module
from app.integration.atlassian import guard, models, ports, startup_check
from tests.fakes import httpx_helpers


class _Auth:
    async def authorize(
        self,
        product: models.Product,  # noqa: ARG002
    ) -> ports.RequestAuth:
        return ports.RequestAuth(base_url="https://site", headers={})


def _run(responses, jira="", confluence=""):
    http, transport = httpx_helpers.make_mock_client(responses)
    client = client_module.AtlassianClient(http=http, auth=_Auth())
    allowlist = guard.StaticAllowlistSource(
        guard.parse_key_list(jira, models.Product.JIRA, env_var="J"),
        guard.parse_key_list(confluence, models.Product.CONFLUENCE, env_var="C"),
    )
    return startup_check.run(client, allowlist), transport


def _ok(json=None):
    return httpx2.Response(200, json=json or {})


class TestCredentials:
    async def test_checks_jira_myself_when_jira_keys_are_listed(self):
        check, transport = _run([_ok(), _ok()], jira="FARM")

        await check

        assert transport.requests[0].url.path == "/rest/api/3/myself"

    async def test_checks_confluence_when_only_spaces_are_listed(self):
        check, transport = _run([_ok(), _ok({"results": [{}]})], confluence="ENG")

        await check

        assert transport.requests[0].url.path == "/wiki/rest/api/user/current"

    async def test_a_401_is_fatal(self):
        check, transport = _run([httpx2.Response(401)], jira="FARM")

        with pytest.raises(
            startup_check.StartupCheckError, match="ATLASSIAN_API_TOKEN"
        ):
            await check

        assert len(transport.requests) == 1

    @pytest.mark.parametrize(
        "failure",
        [httpx2.Response(403), httpx2.Response(503), httpx2.ConnectError("x")],
    )
    async def test_anything_else_only_warns(self, failure, caplog):
        """A missing read-user scope (403) or an outage must not stop the
        server."""
        check, _ = _run([failure, _ok()], jira="FARM")

        with caplog.at_level("WARNING"):
            await check

        assert caplog.records


class TestKeyProbes:
    async def test_probes_each_listed_key(self):
        check, transport = _run(
            [_ok(), _ok(), _ok(), _ok({"results": [{}]})],
            jira="AICE,FARM",
            confluence="ENG",
        )

        await check

        paths = [r.url.path for r in transport.requests[1:]]
        assert paths == [
            "/rest/api/3/project/AICE",
            "/rest/api/3/project/FARM",
            "/wiki/api/v2/spaces",
        ]
        assert transport.requests[3].url.params["keys"] == "ENG"

    async def test_an_unknown_jira_key_warns_without_failing(self, caplog):
        check, _ = _run([_ok(), httpx2.Response(404)], jira="FARM")

        with caplog.at_level("WARNING"):
            await check

        assert "FARM" in caplog.text

    async def test_an_unknown_space_warns_without_failing(self, caplog):
        check, _ = _run([_ok(), _ok({"results": []})], confluence="ENG")

        with caplog.at_level("WARNING"):
            await check

        assert "ENG" in caplog.text

    async def test_no_warning_when_everything_resolves(self, caplog):
        check, _ = _run(
            [_ok(), _ok(), _ok({"results": [{}]})], jira="FARM", confluence="ENG"
        )

        with caplog.at_level("WARNING"):
            await check

        assert caplog.text == ""
