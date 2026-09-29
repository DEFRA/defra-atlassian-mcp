import abc
import dataclasses
import logging

from app.integration.atlassian import models, ports

logger = logging.getLogger(__name__)


class ForbiddenSpaceError(Exception):
    """Raised by a SpaceGuard to deny a user access to a space for a
    product."""


def _parse_csv(value: str, *, env_var: str) -> frozenset[str]:
    keys = frozenset(key.strip() for key in value.split(",") if key.strip())
    if not keys:
        logger.warning(
            "%s has no entries -- every space will be denied for this product "
            "under config_list mode.",
            env_var,
        )
    return keys


@dataclasses.dataclass(frozen=True)
class ConfigAllowList:
    """The hand-managed, per-product allow list backing
    ConfigAllowListSpaceGuard -- parsed once at startup from
    RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS / RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES,
    shared with the read-only /admin/resource-guard endpoint so the portal
    can display the same values that are actually enforced. Both env vars
    are required (though either may be set empty) -- there is no default,
    so a deployment that forgets to set them fails fast at startup rather
    than silently denying everything."""

    jira_projects: frozenset[str]
    confluence_spaces: frozenset[str]

    @classmethod
    def from_csv(cls, jira_csv: str, confluence_csv: str) -> "ConfigAllowList":
        return cls(
            _parse_csv(jira_csv, env_var="RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS"),
            _parse_csv(
                confluence_csv, env_var="RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES"
            ),
        )


class SpaceGuard(abc.ABC):
    """Governance seam: decide whether a user may access a given space or
    project key, for a given Atlassian product.

    Every public method on JiraService and ConfluenceService calls this as
    its first statement, before any token is fetched or vendor call is made.
    The product is part of the question, not an afterthought: a space
    approved for Jira grants nothing in Confluence.
    """

    @abc.abstractmethod
    async def check(
        self, user_id: str, space_key: str, product: models.Product
    ) -> None:
        """Return None to allow; raise ForbiddenSpaceError to deny."""


class AllowAllSpaceGuard(SpaceGuard):
    """Permits access to every space for every product. Opt in explicitly
    via RESOURCE_GUARD_MODE=allow_all -- ConfigAllowListSpaceGuard is the
    default enforcement mode."""

    async def check(
        self,
        user_id: str,  # noqa: ARG002
        space_key: str,  # noqa: ARG002
        product: models.Product,  # noqa: ARG002
    ) -> None:
        return None


class ConfigAllowListSpaceGuard(SpaceGuard):
    """Permits access to space/project keys listed per product in
    ConfigAllowList. Unlike AllowListSpaceGuard, this list is static config
    managed by hand outside the admin portal -- there's no per-user
    approval, but a key listed for one product still grants nothing in the
    other."""

    def __init__(self, allow_list: ConfigAllowList) -> None:
        self._by_product = {
            models.Product.JIRA: allow_list.jira_projects,
            models.Product.CONFLUENCE: allow_list.confluence_spaces,
        }

    async def check(
        self,
        user_id: str,  # noqa: ARG002
        space_key: str,
        product: models.Product,
    ) -> None:
        if space_key not in self._by_product[product]:
            msg = (
                f"{space_key} is not in the configured resource guard allow "
                f"list for {product.value}."
            )
            raise ForbiddenSpaceError(msg)


class AllowListSpaceGuard(SpaceGuard):
    """Permits access only where the user's SpaceAccessRequest for that space
    has been approved for that product (see
    SpaceAccessRequestStore.is_approved)."""

    def __init__(self, store: ports.SpaceAccessRequestStore) -> None:
        self._store = store

    async def check(
        self, user_id: str, space_key: str, product: models.Product
    ) -> None:
        if not await self._store.is_approved(user_id, space_key, product):
            msg = (
                f"No approved access request for {space_key} "
                f"in {product.value}. Request access in the portal first."
            )
            raise ForbiddenSpaceError(msg)
