import logging

import pymongo

logger = logging.getLogger(__name__)


async def check_connection(
    client: pymongo.AsyncMongoClient,  # type: ignore[type-arg]
    database_name: str,
) -> None:
    db_conn = client.get_database(database_name)
    response = await db_conn.command("ping")
    logger.info("MongoDB PING %s", response)
