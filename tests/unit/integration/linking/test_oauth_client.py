import datetime
import json

import httpx2
import pytest

from app import config as app_config
from app.integration.linking import exceptions
from app.integration.linking import models as schemas
from app.integration.linking import oauth_client as oauth_client_module
from tests.fakes import httpx_helpers, in_memory_token_store

_SITES = httpx2.Response(200, json=[{"id": "cloud-1", "name": "example"}])
_CODE_VERIFIER = "test-code-verifier"


def _make_oauth(
    config: app_config.AppConfig,
    responses: list[httpx2.Response | Exception],
    tokens: in_memory_token_store.InMemoryTokenStore | None = None,
) -> tuple[oauth_client_module.OAuthClient, httpx_helpers.MockTransport]:
    client, transport = httpx_helpers.make_mock_client(responses)
    return (
        oauth_client_module.OAuthClient(
            config=config,
            client=client,
            tokens=tokens or in_memory_token_store.InMemoryTokenStore(),
        ),
        transport,
    )


@pytest.fixture
def oauth(fake_config):
    client, _ = httpx_helpers.make_mock_client([])
    return oauth_client_module.OAuthClient(
        config=fake_config,
        client=client,
        tokens=in_memory_token_store.InMemoryTokenStore(),
    )


class TestRedirectUri:
    def test_is_the_configured_absolute_url(self, oauth):
        """Atlassian requires an absolute redirect_uri matching the one
        registered on the OAuth app, and it points at the portal rather than
        at this server -- so it is configuration, not something derived from
        BASE_URL."""
        assert (
            oauth.redirect_uri
            == "http://portal.example.com/account/atlassian-linking/callback"
        )


class TestBuildAuthorizationUrl:
    def test_includes_state(self, oauth):
        url = oauth.build_authorization_url("my-state-token", "my-challenge")

        assert url.startswith("https://auth.atlassian.com/authorize?")
        assert "state=my-state-token" in url
        assert "client_id=test-client-id" in url

    def test_includes_the_pkce_challenge(self, oauth):
        """S256 code_challenge alongside client_secret auth at the token
        endpoint -- defense in depth, not a replacement for it."""
        url = oauth.build_authorization_url("s", "my-challenge")

        assert "code_challenge=my-challenge" in url
        assert "code_challenge_method=S256" in url

    def test_requests_the_api_audience(self, oauth):
        """Without audience=api.atlassian.com the issued token cannot address
        the product APIs at all."""
        assert "audience=api.atlassian.com" in oauth.build_authorization_url("s", "c")

    def test_forces_a_consent_prompt(self, oauth):
        """Atlassian withholds the refresh token for offline_access unless
        consent is prompted explicitly."""
        assert "prompt=consent" in oauth.build_authorization_url("s", "c")


class TestGetValidToken:
    async def test_raises_when_user_has_no_tokens(self, oauth):
        with pytest.raises(exceptions.AtlassianTokenError):
            await oauth.get_valid_token("user-123")

    async def test_returns_access_token_when_not_expired(self, fake_config):
        future_exp = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
        token = schemas.AtlassianToken(
            access_token="example-access-token",
            refresh_token="example-refresh-token",
            expires_at=future_exp,
        )
        store = in_memory_token_store.InMemoryTokenStore({"user-123": token})

        client_obj, _ = _make_oauth(fake_config, [], tokens=store)
        result = await client_obj.get_valid_token("user-123")

        assert result == "example-access-token"

    async def test_returns_access_token_when_expiry_unknown(self, fake_config):
        token = schemas.AtlassianToken(
            access_token="example-access-token",
            refresh_token="example-refresh-token",
            expires_at=None,
        )
        store = in_memory_token_store.InMemoryTokenStore({"user-123": token})

        client_obj, _ = _make_oauth(fake_config, [], tokens=store)
        result = await client_obj.get_valid_token("user-123")

        assert result == "example-access-token"

    async def test_refreshes_and_stores_when_expired(self, fake_config):
        past_exp = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
        new_token_data = {
            "access_token": "example-new-access-token",
            "refresh_token": "example-new-refresh-token",
        }

        old_token = schemas.AtlassianToken(
            access_token="example-access-token",
            refresh_token="example-refresh-token",
            expires_at=past_exp,
            cloud_id="cloud-1",
        )
        store = in_memory_token_store.InMemoryTokenStore({"user-123": old_token})

        client_obj, _ = _make_oauth(
            fake_config,
            [httpx2.Response(200, json=new_token_data)],
            tokens=store,
        )

        result = await client_obj.get_valid_token("user-123")

        assert result == "example-new-access-token"

        stored = await store.get_tokens("user-123")

        assert stored is not None
        assert stored.access_token == "example-new-access-token"
        assert stored.refresh_token == "example-new-refresh-token"

    async def test_carries_the_cloud_id_across_a_refresh(self, fake_config):
        """The refresh response says nothing about the site, so a refresh
        that dropped the cloud id would leave every subsequent product call
        with nothing to address."""
        past_exp = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
        store = in_memory_token_store.InMemoryTokenStore(
            {
                "user-123": schemas.AtlassianToken(
                    access_token="old",
                    refresh_token="old-refresh",
                    expires_at=past_exp,
                    cloud_id="cloud-1",
                )
            }
        )

        client_obj, _ = _make_oauth(
            fake_config,
            [httpx2.Response(200, json={"access_token": "new"})],
            tokens=store,
        )

        credentials = await client_obj.get_valid_credentials("user-123")

        assert credentials.cloud_id == "cloud-1"


class TestExchangeCode:
    async def test_sends_a_json_body(self, fake_config):
        """Atlassian's token endpoint rejects form encoding, which is what
        the client this replaced used."""
        client_obj, transport = _make_oauth(
            fake_config,
            [
                httpx2.Response(200, json={"access_token": "a", "refresh_token": "r"}),
                _SITES,
            ],
        )

        await client_obj.exchange_code("the-code", _CODE_VERIFIER)

        request = transport.requests[0]
        assert request.headers["content-type"] == "application/json"
        body = json.loads(request.content)
        assert body["grant_type"] == "authorization_code"
        assert body["code_verifier"] == _CODE_VERIFIER

    async def test_resolves_the_cloud_id(self, fake_config):
        client_obj, _ = _make_oauth(
            fake_config,
            [
                httpx2.Response(200, json={"access_token": "a", "refresh_token": "r"}),
                _SITES,
            ],
        )

        token = await client_obj.exchange_code("the-code", _CODE_VERIFIER)

        assert token.cloud_id == "cloud-1"

    async def test_raises_when_the_account_can_reach_no_site(self, fake_config):
        client_obj, _ = _make_oauth(
            fake_config,
            [
                httpx2.Response(200, json={"access_token": "a", "refresh_token": "r"}),
                httpx2.Response(200, json=[]),
            ],
        )

        with pytest.raises(exceptions.NoAccessibleSiteError):
            await client_obj.exchange_code("the-code", _CODE_VERIFIER)

    async def test_raises_api_error_on_http_error(self, fake_config):
        client_obj, _ = _make_oauth(fake_config, [httpx2.Response(400)])

        with pytest.raises(exceptions.AtlassianApiError) as exc_info:
            await client_obj.exchange_code("bad-code", _CODE_VERIFIER)

        assert exc_info.value.status_code == 400

    async def test_raises_unavailable_error_when_unreachable(self, fake_config):
        client_obj, _ = _make_oauth(
            fake_config, [httpx2.ConnectError("Connection refused")]
        )

        with pytest.raises(exceptions.AtlassianUnavailableError):
            await client_obj.exchange_code("bad-code", _CODE_VERIFIER)


class TestRefresh:
    async def test_reuses_original_token_when_response_lacks_one(self, fake_config):
        client_obj, _ = _make_oauth(
            fake_config,
            [httpx2.Response(200, json={"access_token": "new-access"})],
        )
        token = await client_obj.refresh("original-refresh")
        assert token.access_token == "new-access"
        assert token.refresh_token == "original-refresh"

    async def test_uses_new_refresh_token_when_response_provides_one(self, fake_config):
        """Atlassian rotates refresh tokens, so the new one has to win."""
        client_obj, _ = _make_oauth(
            fake_config,
            [
                httpx2.Response(
                    200,
                    json={"access_token": "new-access", "refresh_token": "new-refresh"},
                )
            ],
        )
        token = await client_obj.refresh("original-refresh")
        assert token.refresh_token == "new-refresh"

    async def test_raises_api_error_on_http_error(self, fake_config):
        client_obj, _ = _make_oauth(fake_config, [httpx2.Response(401)])
        with pytest.raises(exceptions.AtlassianApiError) as exc_info:
            await client_obj.refresh("original-refresh")
        assert exc_info.value.status_code == 401

    async def test_raises_unavailable_error_when_unreachable(self, fake_config):
        client_obj, _ = _make_oauth(
            fake_config, [httpx2.ConnectError("Connection refused")]
        )
        with pytest.raises(exceptions.AtlassianUnavailableError):
            await client_obj.refresh("original-refresh")
