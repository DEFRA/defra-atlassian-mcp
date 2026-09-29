import datetime
import unittest.mock

import pytest
from pymongo import common as pymongo_common

from app.integration.atlassian import models
from app.integration.atlassian import mongo_store as approval_store

_NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

JIRA = models.Product.JIRA
CONFLUENCE = models.Product.CONFLUENCE


def _make_request(**kwargs: object) -> models.SpaceAccessRequest:
    defaults: dict[str, object] = {
        "id": "req-123",
        "user_id": "usr_abc",
        "space_key": "FARM",
        "reason": "need it for a workshop",
        "iao": "owner@defra.gov.uk",
        "products": models.empty_products(),
        "created_at": _NOW,
    }
    defaults.update(kwargs)
    return models.SpaceAccessRequest(**defaults)  # type: ignore[arg-type]


class TestDocumentShape:
    async def test_stores_enum_keys_and_values_as_plain_strings(self) -> None:
        """BSON cannot encode an Enum, and here the product enum is a
        document key as well as a value."""
        mock_col = unittest.mock.AsyncMock()
        store = approval_store.MongoSpaceAccessRequestStore(mock_col)
        products = models.empty_products()
        products[JIRA] = models.ProductApproval(
            requested=True, status=models.ProductStatus.PENDING
        )

        await store.create(_make_request(products=products))

        doc = mock_col.insert_one.await_args[0][0]
        assert set(doc["products"]) == {"jira", "confluence"}
        assert doc["products"]["jira"]["status"] == "pending"
        assert doc["products"]["confluence"]["status"] == "not-requested"

    async def test_keeps_datetimes_as_datetimes(self) -> None:
        """model_dump(mode="json") would leave ISO strings behind, which
        Mongo cannot sort or index as dates."""
        mock_col = unittest.mock.AsyncMock()
        store = approval_store.MongoSpaceAccessRequestStore(mock_col)

        await store.create(_make_request())

        doc = mock_col.insert_one.await_args[0][0]
        assert doc["created_at"] == _NOW

    async def test_replacement_is_valid_for_real_pymongo(self) -> None:
        """A mocked collection accepts any arguments, so a replacement
        containing $ operators would look fine here even though real pymongo
        rejects it."""
        mock_col = unittest.mock.AsyncMock()
        store = approval_store.MongoSpaceAccessRequestStore(mock_col)

        await store.update(_make_request())

        pymongo_common.validate_ok_for_replace(mock_col.replace_one.await_args[0][1])


class TestQueries:
    async def test_get_projects_out_the_mongo_id(self) -> None:
        mock_col = unittest.mock.AsyncMock()
        mock_col.find_one.return_value = None
        store = approval_store.MongoSpaceAccessRequestStore(mock_col)

        assert await store.get("nope") is None
        mock_col.find_one.assert_awaited_once_with({"id": "nope"}, {"_id": 0})

    async def test_is_approved_asks_about_one_product(self) -> None:
        mock_col = unittest.mock.AsyncMock()
        mock_col.find_one.return_value = {"_id": 1}
        store = approval_store.MongoSpaceAccessRequestStore(mock_col)

        assert await store.is_approved("usr_abc", "FARM", CONFLUENCE) is True
        assert mock_col.find_one.await_args[0][0] == {
            "user_id": "usr_abc",
            "space_key": "FARM",
            "products.confluence.status": "approved",
        }

    async def test_list_pending_matches_any_product(self) -> None:
        mock_col = unittest.mock.MagicMock()
        mock_col.find.return_value = _empty_cursor()
        store = approval_store.MongoSpaceAccessRequestStore(mock_col)

        await store.list_pending()

        assert mock_col.find.call_args[0][0] == {
            "$or": [
                {"products.jira.status": "pending"},
                {"products.confluence.status": "pending"},
            ]
        }


def _empty_cursor():
    class _Cursor:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    return _Cursor()


@pytest.mark.mongo
class TestAgainstRealMongo:
    async def test_round_trips_a_request_with_tz_aware_dates(self, mongo_db) -> None:
        store = approval_store.MongoSpaceAccessRequestStore(mongo_db["approvals"])
        products = models.empty_products()
        products[JIRA] = models.ProductApproval(
            requested=True,
            status=models.ProductStatus.APPROVED,
            reviewer_id="usr_iao",
            decided_at=_NOW,
        )
        await store.create(_make_request(products=products))

        found = await store.get("req-123")

        assert found is not None
        assert found.product(JIRA).decided_at == _NOW
        assert found.created_at == _NOW

    async def test_one_request_per_user_and_space(self, mongo_db) -> None:
        """The service checks before writing, but that check is not atomic --
        the unique index is what actually stops two concurrent first-time
        requests both inserting."""
        import pymongo.errors

        store = approval_store.MongoSpaceAccessRequestStore(mongo_db["approvals"])
        await store.ensure_indexes()
        await store.create(_make_request())

        with pytest.raises(pymongo.errors.DuplicateKeyError):
            await store.create(_make_request(id="req-456"))

    async def test_finds_a_pending_request_by_either_product(self, mongo_db) -> None:
        store = approval_store.MongoSpaceAccessRequestStore(mongo_db["approvals"])
        products = models.empty_products()
        products[CONFLUENCE] = models.ProductApproval(
            requested=True, status=models.ProductStatus.PENDING
        )
        await store.create(_make_request(products=products))

        assert [r.id for r in await store.list_pending()] == ["req-123"]
