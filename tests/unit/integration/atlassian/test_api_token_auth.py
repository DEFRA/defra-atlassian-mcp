import base64

import httpx2
import pydantic
import pytest

from app.integration.atlassian import api_token_auth, models
from tests.fakes import httpx_helpers

_TOKEN = pydantic.SecretStr("s3cret")
_BASIC = "Basic " + base64.b64encode(b"dev@example.com:s3cret").decode()


class TestClassic:
    @pytest.mark.parametrize("product", list(models.Product))
    async def test_addresses_the_site_for_every_product(self, product):
        """The services' paths carry /rest/api/3 or /wiki themselves."""
        auth = api_token_auth.ApiTokenAtlassianAuth.classic(
            "https://example.atlassian.net/", "dev@example.com", _TOKEN
        )

        request_auth = await auth.authorize(product)

        assert request_auth.base_url == "https://example.atlassian.net"

    async def test_uses_basic_auth_with_email_and_token(self):
        auth = api_token_auth.ApiTokenAtlassianAuth.classic(
            "https://example.atlassian.net", "dev@example.com", _TOKEN
        )

        request_auth = await auth.authorize(models.Product.JIRA)

        assert dict(request_auth.headers) == {"Authorization": _BASIC}


class TestScoped:
    @pytest.mark.parametrize(
        ("product", "segment"),
        [(models.Product.JIRA, "jira"), (models.Product.CONFLUENCE, "confluence")],
    )
    async def test_addresses_the_gateway_by_product_and_cloud_id(
        self, product, segment
    ):
        auth = api_token_auth.ApiTokenAtlassianAuth.scoped(
            "cloud-1", "dev@example.com", _TOKEN
        )

        request_auth = await auth.authorize(product)

        assert request_auth.base_url == (
            f"https://api.atlassian.com/ex/{segment}/cloud-1"
        )

    async def test_also_uses_basic_auth(self):
        auth = api_token_auth.ApiTokenAtlassianAuth.scoped(
            "cloud-1", "dev@example.com", _TOKEN
        )

        request_auth = await auth.authorize(models.Product.CONFLUENCE)

        assert request_auth.headers["Authorization"] == _BASIC


def test_repr_does_not_render_the_credentials():
    auth = api_token_auth.ApiTokenAtlassianAuth.classic(
        "https://example.atlassian.net", "dev@example.com", _TOKEN
    )

    assert "s3cret" not in repr(auth)
    assert _BASIC.split()[1] not in repr(auth)


class TestResolveCloudId:
    async def test_reads_the_cloud_id_from_tenant_info(self):
        http, transport = httpx_helpers.make_mock_client(
            [httpx2.Response(200, json={"cloudId": "cloud-1"})]
        )

        cloud_id = await api_token_auth.resolve_cloud_id(
            http, "https://example.atlassian.net/"
        )

        assert cloud_id == "cloud-1"
        assert str(transport.requests[0].url) == (
            "https://example.atlassian.net/_edge/tenant_info"
        )

    async def test_sends_no_credentials(self):
        http, transport = httpx_helpers.make_mock_client(
            [httpx2.Response(200, json={"cloudId": "cloud-1"})]
        )

        await api_token_auth.resolve_cloud_id(http, "https://example.atlassian.net")

        assert "Authorization" not in transport.requests[0].headers

    @pytest.mark.parametrize(
        "response",
        [
            httpx2.Response(404),
            httpx2.Response(200, json={}),
            httpx2.Response(200, json={"cloudId": ""}),
            httpx2.Response(200, json=["not", "an", "object"]),
            httpx2.ConnectError("nope"),
        ],
    )
    async def test_any_failure_is_a_lookup_error(self, response):
        http, _ = httpx_helpers.make_mock_client([response])

        with pytest.raises(api_token_auth.CloudIdLookupError):
            await api_token_auth.resolve_cloud_id(http, "https://example.atlassian.net")
