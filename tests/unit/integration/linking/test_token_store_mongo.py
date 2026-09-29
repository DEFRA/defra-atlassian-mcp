"""Round-trip coverage for MongoTokenStore against a real MongoDB (see
tests/support/mongo.py). The AsyncMock version in test_token_store.py
validates the document shape with pymongo's own validator, but a mock can't
catch datetime tz-awareness surviving a real round trip -- this closes that
one class of bug permanently.
"""

import datetime

import pytest

from app.integration.linking import models, mongo_store

pytestmark = pytest.mark.mongo


class TestStoreTokens:
    async def test_round_trips_a_tz_aware_expiry(self, mongo_db):
        store = mongo_store.MongoTokenStore(mongo_db["atlassian_tokens"])
        expires_at = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
        token = models.AtlassianToken(
            access_token="example-access-token",
            refresh_token="example-refresh-token",
            expires_at=expires_at,
        )

        await store.store_tokens("user-123", token)
        result = await store.get_tokens("user-123")

        assert result is not None
        assert result.expires_at is not None
        assert result.expires_at.tzinfo is not None
        assert result.expires_at == expires_at

    async def test_replaces_rather_than_duplicates(self, mongo_db):
        store = mongo_store.MongoTokenStore(mongo_db["atlassian_tokens"])
        first = models.AtlassianToken(
            access_token="example-access-token-1",
            refresh_token="example-refresh-token-1",
        )
        second = models.AtlassianToken(
            access_token="example-access-token-2",
            refresh_token="example-refresh-token-2",
        )

        await store.store_tokens("user-123", first)
        await store.store_tokens("user-123", second)
        result = await store.get_tokens("user-123")

        assert result is not None
        assert result.access_token == "example-access-token-2"
        assert (
            await mongo_db["atlassian_tokens"].count_documents({"user_id": "user-123"})
            == 1
        )


class TestGetTokens:
    async def test_returns_none_when_absent(self, mongo_db):
        store = mongo_store.MongoTokenStore(mongo_db["atlassian_tokens"])

        assert await store.get_tokens("no-such-user") is None


class TestDeleteTokens:
    async def test_removes_the_document(self, mongo_db):
        store = mongo_store.MongoTokenStore(mongo_db["atlassian_tokens"])
        await store.store_tokens(
            "user-123", models.AtlassianToken(access_token="a", refresh_token="b")
        )

        await store.delete_tokens("user-123")

        assert await store.get_tokens("user-123") is None
