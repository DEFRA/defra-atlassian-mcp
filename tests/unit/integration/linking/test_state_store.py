import datetime
import unittest.mock
import uuid

import pytest

from app.integration.linking import exceptions, pkce
from app.integration.linking import mongo_store as state_store


class TestIssue:
    async def test_inserts_a_document_and_returns_a_uuid_string(self) -> None:
        mock_collection = unittest.mock.AsyncMock()
        store = state_store.MongoOAuthStateStore(mock_collection)

        issued = await store.issue("user-123")

        uuid.UUID(issued.state)
        mock_collection.insert_one.assert_awaited_once()
        doc = mock_collection.insert_one.await_args[0][0]
        assert doc["_id"] == issued.state
        assert doc["user_id"] == "user-123"

    async def test_stores_a_code_verifier_and_returns_its_challenge(self) -> None:
        mock_collection = unittest.mock.AsyncMock()
        store = state_store.MongoOAuthStateStore(mock_collection)

        issued = await store.issue("user-123")

        doc = mock_collection.insert_one.await_args[0][0]
        assert doc["code_verifier"]
        assert issued.code_challenge == pkce.derive_code_challenge(doc["code_verifier"])

    async def test_sets_expires_at_from_clock_and_ttl(self) -> None:
        now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        mock_collection = unittest.mock.AsyncMock()
        store = state_store.MongoOAuthStateStore(
            mock_collection, clock=lambda: now, ttl=datetime.timedelta(minutes=5)
        )

        await store.issue("user-123")

        doc = mock_collection.insert_one.await_args[0][0]
        assert doc["expires_at"] == now + datetime.timedelta(minutes=5)


class TestConsume:
    async def test_returns_oauth_state_for_issued_token(self) -> None:
        now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        mock_collection = unittest.mock.AsyncMock()
        mock_collection.find_one_and_delete.return_value = {
            "_id": "state-123",
            "user_id": "user-123",
            "code_verifier": "verifier-abc",
            "expires_at": now + datetime.timedelta(minutes=5),
        }
        store = state_store.MongoOAuthStateStore(mock_collection, clock=lambda: now)

        result = await store.consume("state-123")

        assert result.user_id == "user-123"
        assert result.code_verifier == "verifier-abc"
        mock_collection.find_one_and_delete.assert_awaited_once_with(
            {"_id": "state-123"}
        )

    async def test_rejects_unknown_state(self) -> None:
        mock_collection = unittest.mock.AsyncMock()
        mock_collection.find_one_and_delete.return_value = None
        store = state_store.MongoOAuthStateStore(mock_collection)

        with pytest.raises(exceptions.OAuthStateError, match="Invalid or unknown"):
            await store.consume("not-a-real-state")

    async def test_rejects_expired_state(self) -> None:
        issued_at = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        now = issued_at + datetime.timedelta(minutes=10)
        mock_collection = unittest.mock.AsyncMock()
        mock_collection.find_one_and_delete.return_value = {
            "_id": "state-123",
            "user_id": "user-123",
            "code_verifier": "verifier-abc",
            "expires_at": issued_at + datetime.timedelta(minutes=5),
        }
        store = state_store.MongoOAuthStateStore(mock_collection, clock=lambda: now)

        with pytest.raises(exceptions.OAuthStateError, match="expired"):
            await store.consume("state-123")


class TestEnsureIndexes:
    async def test_creates_ttl_index_on_expires_at(self) -> None:
        mock_collection = unittest.mock.AsyncMock()
        store = state_store.MongoOAuthStateStore(mock_collection)

        await store.ensure_indexes()

        mock_collection.create_index.assert_awaited_once_with(
            "expires_at", expireAfterSeconds=0
        )
