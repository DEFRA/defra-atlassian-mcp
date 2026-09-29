from pymongo.asynchronous import collection

from app.integration.atlassian import models, ports


def _product_status_field(product: models.Product) -> str:
    return f"products.{product.value}.status"


class MongoSpaceAccessRequestStore(ports.SpaceAccessRequestStore):
    def __init__(self, col: collection.AsyncCollection) -> None:  # type: ignore[type-arg]
        self._collection = col

    async def ensure_indexes(self) -> None:
        """One request per (user, space). The unique index is what actually
        enforces it -- SpaceAccessRequestService checks before writing, but
        that check is not atomic, so two concurrent first-time requests for
        the same space would otherwise both insert."""
        await self._collection.create_index(
            [("user_id", 1), ("space_key", 1)], unique=True
        )

    async def create(self, request: models.SpaceAccessRequest) -> None:
        await self._collection.insert_one(self._to_doc(request))

    async def get(self, request_id: str) -> models.SpaceAccessRequest | None:
        doc = await self._collection.find_one({"id": request_id}, {"_id": 0})
        if doc is None:
            return None
        return models.SpaceAccessRequest.model_validate(doc)

    async def get_for_user_and_space(
        self, user_id: str, space_key: str
    ) -> models.SpaceAccessRequest | None:
        doc = await self._collection.find_one(
            {"user_id": user_id, "space_key": space_key},
            {"_id": 0},
        )
        if doc is None:
            return None
        return models.SpaceAccessRequest.model_validate(doc)

    async def list_for_user(self, user_id: str) -> list[models.SpaceAccessRequest]:
        cursor = self._collection.find({"user_id": user_id}, {"_id": 0})
        return [models.SpaceAccessRequest.model_validate(doc) async for doc in cursor]

    async def list_pending(self) -> list[models.SpaceAccessRequest]:
        cursor = self._collection.find(
            {
                "$or": [
                    {_product_status_field(product): models.ProductStatus.PENDING.value}
                    for product in models.Product
                ]
            },
            {"_id": 0},
        )
        return [models.SpaceAccessRequest.model_validate(doc) async for doc in cursor]

    async def update(self, request: models.SpaceAccessRequest) -> None:
        await self._collection.replace_one({"id": request.id}, self._to_doc(request))

    async def is_approved(
        self, user_id: str, space_key: str, product: models.Product
    ) -> bool:
        doc = await self._collection.find_one(
            {
                "user_id": user_id,
                "space_key": space_key,
                _product_status_field(product): models.ProductStatus.APPROVED.value,
            },
            {"_id": 1},
        )
        return doc is not None

    @staticmethod
    def _to_doc(request: models.SpaceAccessRequest) -> dict:  # type: ignore[type-arg]
        """Persist snake_case field names -- the camelCase aliases are the
        wire format, not the storage format.

        Dumped in JSON mode so enums land as plain strings (BSON cannot encode
        an Enum, and the product enum is a document *key* here), then the
        datetimes are put back as real datetimes so Mongo stores BSON dates
        rather than ISO strings.
        """
        doc = request.model_dump(mode="json")
        doc["created_at"] = request.created_at
        for product, approval in request.products.items():
            doc["products"][product.value]["decided_at"] = approval.decided_at
        return doc
