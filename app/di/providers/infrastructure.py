import logging
import os
from collections.abc import AsyncIterator

import dishka
import pymongo
from pymongo.asynchronous import database

from app import config as app_config
from app.common import mongo, tls

logger = logging.getLogger(__name__)

_MONGO_DATABASE = "atlassian-mcp"


class InfrastructureProvider(dishka.Provider):
    @dishka.provide(scope=dishka.Scope.APP)
    def provide_custom_ca_certs(self) -> dict[str, str]:
        return tls.extract_all_certs(os.environ)

    @dishka.provide(scope=dishka.Scope.APP)
    async def provide_mongo_client(
        self,
        config: app_config.AppConfig,
        custom_ca_certs: dict[str, str],
    ) -> AsyncIterator[pymongo.AsyncMongoClient]:  # type: ignore[type-arg]
        cert = custom_ca_certs.get(config.mongo_truststore)
        client: pymongo.AsyncMongoClient  # type: ignore[type-arg]
        if cert:
            logger.info(
                "Creating MongoDB client with custom TLS cert %s",
                config.mongo_truststore,
            )
            client = pymongo.AsyncMongoClient(
                config.mongo_uri, tlsCAFile=cert, tz_aware=True
            )
        else:
            logger.info("Creating MongoDB client")
            client = pymongo.AsyncMongoClient(config.mongo_uri, tz_aware=True)

        logger.info("Testing MongoDB connection to %s", config.mongo_uri)
        await mongo.check_connection(client, _MONGO_DATABASE)
        yield client
        await client.close()
        logger.info("MongoDB client closed")

    @dishka.provide(scope=dishka.Scope.APP)
    def provide_mongo_db(
        self,
        client: pymongo.AsyncMongoClient,  # type: ignore[type-arg]
    ) -> database.AsyncDatabase:  # type: ignore[type-arg]
        return client.get_database(_MONGO_DATABASE)
