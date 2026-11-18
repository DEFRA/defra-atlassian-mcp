import pytest

from app.integration.atlassian import errors, models
from app.integration.linking import oauth_auth
from tests.fakes import fake_oauth_client


def _auth(token: str | None = "tok", cloud_id: str | None = "cloud-1"):
    oauth = fake_oauth_client.FakeOAuthClient(token, cloud_id=cloud_id)
    return oauth_auth.OAuthAtlassianAuth("usr_a", oauth, "https://api.atlassian.com/")


class TestOAuthAtlassianAuth:
    @pytest.mark.parametrize(
        ("product", "segment"),
        [(models.Product.JIRA, "jira"), (models.Product.CONFLUENCE, "confluence")],
    )
    async def test_addresses_the_gateway_by_product_and_cloud_id(
        self, product, segment
    ):
        auth = await _auth().authorize(product)

        assert auth.base_url == f"https://api.atlassian.com/ex/{segment}/cloud-1"

    async def test_sends_the_access_token_as_a_bearer(self):
        auth = await _auth().authorize(models.Product.JIRA)

        assert dict(auth.headers) == {"Authorization": "Bearer tok"}

    async def test_an_unlinked_user_is_told_to_connect_in_the_portal(self):
        """The tools pass this message straight to the MCP caller, so it
        must say what to do and must not carry the user id."""
        with pytest.raises(errors.AtlassianCredentialsError) as exc_info:
            await _auth(token=None).authorize(models.Product.JIRA)

        assert "connect your Atlassian account" in str(exc_info.value)
        assert "usr_a" not in str(exc_info.value)

    async def test_a_token_with_no_site_says_so(self):
        with pytest.raises(errors.AtlassianCredentialsError) as exc_info:
            await _auth(cloud_id=None).authorize(models.Product.JIRA)

        assert "no sites" in str(exc_info.value)
        assert "usr_a" not in str(exc_info.value)
