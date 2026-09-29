import unittest.mock

from pymongo import common as pymongo_common

from app.integration.linking import models as schemas
from app.integration.linking import mongo_store as token_store


class TestStoreTokens:
    async def test_replace_one_called_with_the_right_filter_and_document(self) -> None:
        mock_collection = unittest.mock.AsyncMock()
        store = token_store.MongoTokenStore(mock_collection)
        token = schemas.AtlassianToken(access_token="test", refresh_token="test")
        await store.store_tokens("user-123", token)
        mock_collection.replace_one.assert_awaited_once()
        args = mock_collection.replace_one.await_args
        assert args[0][0] == {"user_id": "user-123"}
        assert args[0][1] == {
            "user_id": "user-123",
            "access_token": "test",
            "refresh_token": "test",
            "expires_at": None,
            "cloud_id": None,
        }
        assert args[1]["upsert"] is True

    async def test_replacement_is_valid_for_real_pymongo(self) -> None:
        """Regression guard: a mocked collection accepts any arguments, so a
        call like ``replace_one(filter, {"$set": doc}, upsert=True)`` looks
        correct here even though real pymongo rejects a replacement document
        containing $ operators. Validate the second positional argument the
        same way pymongo's AsyncCollection.replace_one does, to catch that
        class of bug without a live MongoDB.
        """
        mock_collection = unittest.mock.AsyncMock()
        store = token_store.MongoTokenStore(mock_collection)
        token = schemas.AtlassianToken(access_token="test", refresh_token="test")
        await store.store_tokens("user-123", token)
        replacement = mock_collection.replace_one.await_args[0][1]
        pymongo_common.validate_ok_for_replace(replacement)


class TestGetTokens:
    async def test_found(self) -> None:
        mock_collection = unittest.mock.AsyncMock()
        mock_collection.find_one.return_value = {
            "user_id": "user-123",
            "access_token": "test",
            "refresh_token": "test",
        }
        store = token_store.MongoTokenStore(mock_collection)
        result = await store.get_tokens("user-123")
        assert result is not None
        assert result.access_token == "test"
        assert result.refresh_token == "test"

    async def test_not_found(self) -> None:
        mock_collection = unittest.mock.AsyncMock()
        mock_collection.find_one.return_value = None
        store = token_store.MongoTokenStore(mock_collection)
        result = await store.get_tokens("user-123")
        assert result is None


class TestDeleteTokens:
    async def test_delete_one_called_with_the_right_filter(self) -> None:
        mock_collection = unittest.mock.AsyncMock()
        store = token_store.MongoTokenStore(mock_collection)
        await store.delete_tokens("user-123")
        mock_collection.delete_one.assert_awaited_once_with({"user_id": "user-123"})
