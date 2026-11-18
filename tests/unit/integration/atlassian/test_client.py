import ast
import pathlib

import httpx2
import pytest

from app.integration.atlassian import client as client_module
from app.integration.atlassian import errors, models, ports
from tests.fakes import httpx_helpers


class _FixedAuth:
    """An AtlassianAuth that records what it was asked for."""

    def __init__(self, base_url: str = "https://site.example/api") -> None:
        self.asked: list[models.Product] = []
        self._base_url = base_url

    async def authorize(self, product: models.Product) -> ports.RequestAuth:
        self.asked.append(product)
        return ports.RequestAuth(
            base_url=self._base_url, headers={"Authorization": "Basic abc"}
        )


def _client(responses):
    http, transport = httpx_helpers.make_mock_client(responses)
    auth = _FixedAuth()
    return client_module.AtlassianClient(http=http, auth=auth), auth, transport


class TestGet:
    async def test_appends_the_path_to_the_auths_base_url(self):
        client, _, transport = _client([httpx2.Response(200, json={})])

        await client.get(models.Product.JIRA, "/rest/api/3/myself", {"a": "1"})

        assert str(transport.requests[0].url) == (
            "https://site.example/api/rest/api/3/myself?a=1"
        )

    async def test_asks_the_auth_for_the_product_being_called(self):
        client, auth, _ = _client([httpx2.Response(200, json={})])

        await client.get(models.Product.CONFLUENCE, "/wiki/x")

        assert auth.asked == [models.Product.CONFLUENCE]

    async def test_sends_the_auths_headers_and_asks_for_json(self):
        client, _, transport = _client([httpx2.Response(200, json={})])

        await client.get(models.Product.JIRA, "/x")

        headers = transport.requests[0].headers
        assert headers["Authorization"] == "Basic abc"
        assert headers["Accept"] == "application/json"

    async def test_returns_the_decoded_body(self):
        client, _, _ = _client([httpx2.Response(200, json={"key": "FARM-1"})])

        assert await client.get(models.Product.JIRA, "/x") == {"key": "FARM-1"}

    async def test_a_non_2xx_becomes_an_api_error_without_the_body(self):
        client, _, _ = _client([httpx2.Response(404, text="secret vendor detail")])

        with pytest.raises(errors.AtlassianApiError) as exc_info:
            await client.get(models.Product.JIRA, "/x")

        assert exc_info.value.status_code == 404
        assert "secret vendor detail" not in str(exc_info.value)

    async def test_a_transport_failure_becomes_an_unavailable_error(self):
        client, _, _ = _client([httpx2.ConnectError("nope")])

        with pytest.raises(errors.AtlassianUnavailableError):
            await client.get(models.Product.JIRA, "/x")


class TestImports:
    def test_client_does_not_import_the_linking_package(self):
        """The client is shared with the stdio entry point, which has no
        OAuth linking. AST check, so it holds regardless of import order."""
        source = pathlib.Path(client_module.__file__).read_text()
        modules = {
            node.module
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any(m.startswith("app.integration.linking") for m in modules)
