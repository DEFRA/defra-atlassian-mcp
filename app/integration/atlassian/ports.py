import abc
import dataclasses
from collections.abc import Mapping
from typing import Protocol

from app.integration.atlassian import models


@dataclasses.dataclass(frozen=True, slots=True)
class RequestAuth:
    """Where to send one product's API calls, and how to authenticate them.

    ``base_url`` is the product's API root with no trailing slash -- the
    paths the services pass (``/rest/api/3/...``, ``/wiki/...``) are
    appended to it as-is. ``headers`` carries the Authorization header.
    """

    base_url: str
    headers: Mapping[str, str]


class AtlassianAuth(Protocol):
    """Supplies the address and credentials for Atlassian API calls.

    The client and the product services depend only on this, so neither
    knows whether a call is authorised by a user's OAuth token (HTTP entry
    point) or by an API token (stdio entry point). An implementation that
    cannot supply credentials raises errors.AtlassianCredentialsError.
    """

    async def authorize(self, product: models.Product) -> RequestAuth: ...


class SpaceAccessRequestStore(abc.ABC):
    @abc.abstractmethod
    async def create(self, request: models.SpaceAccessRequest) -> None: ...

    @abc.abstractmethod
    async def get(self, request_id: str) -> models.SpaceAccessRequest | None: ...

    @abc.abstractmethod
    async def get_for_user_and_space(
        self, user_id: str, space_key: str
    ) -> models.SpaceAccessRequest | None: ...

    @abc.abstractmethod
    async def list_for_user(self, user_id: str) -> list[models.SpaceAccessRequest]: ...

    @abc.abstractmethod
    async def list_pending(self) -> list[models.SpaceAccessRequest]: ...

    @abc.abstractmethod
    async def update(self, request: models.SpaceAccessRequest) -> None: ...

    @abc.abstractmethod
    async def is_approved(
        self, user_id: str, space_key: str, product: models.Product
    ) -> bool: ...
