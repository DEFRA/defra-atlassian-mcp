import datetime

import pytest

from app.common import http_client
from app.integration.linking import oauth_client
from tests.fakes import in_memory_token_store
from tests.support import vcr_config


def _make_client(config) -> oauth_client.OAuthClient:
    return oauth_client.OAuthClient(
        config=config,
        client=http_client.create_async_client(
            tracing_header=config.tracing_header,
            trace_id="test-trace",
        ),
        tokens=in_memory_token_store.InMemoryTokenStore(),
    )


class TestExchangeCode:
    @pytest.mark.vcr("atlassian_exchange_code")
    async def test_via_cassette(self, fake_config) -> None:
        """access_token/refresh_token are scrubbed to vcr_config.PLACEHOLDER by
        before_record_response, which runs on every cassette load (not just
        fresh recording) -- so this asserts the real parsing pipeline read
        those fields at all, and that expires_at was computed from the
        recording's real expires_in, not that a specific secret round-tripped.
        """
        client = _make_client(fake_config)

        token = await client.exchange_code("auth_code_123", "test-code-verifier")

        assert token.access_token == vcr_config.PLACEHOLDER
        assert token.refresh_token == vcr_config.PLACEHOLDER
        assert token.expires_at is not None
        assert token.expires_at > datetime.datetime.now(datetime.UTC)
        # The cloud id is not in the token response at all -- it comes from
        # the follow-up accessible-resources call, the second interaction in
        # this cassette.
        assert token.cloud_id == "11223344-a1b2-3b4c-5d6e-f7a8b9c0d1e2"


class TestRefresh:
    @pytest.mark.vcr("atlassian_refresh_token")
    async def test_via_cassette(self, fake_config) -> None:
        client = _make_client(fake_config)

        token = await client.refresh("refresh_token_123")

        assert token.access_token == vcr_config.PLACEHOLDER
        assert token.refresh_token == vcr_config.PLACEHOLDER
        assert token.expires_at is not None
        assert token.expires_at > datetime.datetime.now(datetime.UTC)
