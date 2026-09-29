"""Live MongoDB behind @pytest.mark.mongo (see docs/python-testing-standard.md).

The AsyncMock-based store tests (test_mongo_store.py, test_token_store.py,
test_state_store.py, test_space_access_request_store.py) validate documents
against pymongo's own validators, but three classes of bug stay invisible to
a mock no matter how it's hardened: datetime tz-awareness round-tripping,
_id projection behaviour, and index semantics. A round-trip test against a
real MongoDB closes that class permanently.

The container starts once per session (~2-5s) -- the one documented,
measured exception to "all fixtures are function-scoped" (see
docs/python-testing-standard.md §2.5). Each test still gets its own
database, function-scoped, so no state crosses tests.
"""

import uuid
from collections.abc import AsyncIterator

import pymongo
import pytest
from pymongo.asynchronous import database
from testcontainers.community.mongodb import MongoDbContainer


@pytest.fixture(scope="session")
def _mongo_container() -> AsyncIterator[MongoDbContainer]:
    with MongoDbContainer("mongo:6.0.13") as container:
        yield container


@pytest.fixture
async def mongo_db(
    _mongo_container: MongoDbContainer,
) -> AsyncIterator[database.AsyncDatabase]:  # type: ignore[type-arg]
    client: pymongo.AsyncMongoClient = pymongo.AsyncMongoClient(  # type: ignore[type-arg]
        _mongo_container.get_connection_url(), tz_aware=True
    )
    db = client.get_database(f"test-{uuid.uuid4().hex}")
    try:
        yield db
    finally:
        await client.drop_database(db.name)
        await client.close()
