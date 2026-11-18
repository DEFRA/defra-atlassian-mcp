"""Access policy: which Jira projects and Confluence spaces may be read.

Every public method on JiraService and ConfluenceService calls
AccessPolicy.check as its first statement, before any credentials are
fetched or vendor call is made. The product is part of the question: a key
allowed for Jira grants nothing in Confluence.

There is one policy, AllowlistAccessPolicy, over two sources:

- StaticAllowlistSource -- a fixed, validated list from settings. Used by
  the stdio entry point, and by the HTTP entry point in ``config_list`` mode.
- ApprovedRequestsAllowlistSource (approved_requests_source.py) -- the
  calling user's approved access requests. HTTP only, ``allow_list`` mode.

Neither the policy nor the services see a user id. Where the answer depends
on the user, the source is built per request already bound to them.
"""

import dataclasses
import logging
import re
from typing import Protocol

from app.integration.atlassian import models

logger = logging.getLogger(__name__)

# Matching is exact and case-sensitive. Jira project keys are upper case;
# Confluence space keys are alphanumeric, which deliberately excludes
# personal spaces (``~accountid``).
_KEY_PATTERNS = {
    models.Product.JIRA: re.compile(r"[A-Z][A-Z0-9_]+\Z"),
    models.Product.CONFLUENCE: re.compile(r"[A-Za-z0-9]+\Z"),
}


class ForbiddenResourceError(Exception):
    """Raised by an AccessPolicy to deny access to a project or space for a
    product. Its message is written for the caller (it reaches an LLM as a
    ToolError)."""


# The old name, kept for existing imports. Same class.
ForbiddenSpaceError = ForbiddenResourceError


class AllowlistSource(Protocol):
    """Answers whether one key is allowed for one product."""

    async def contains(self, product: models.Product, key: str) -> bool: ...

    def denial_message(self, product: models.Product, key: str) -> str:
        """What to tell the caller when ``key`` is not allowed -- each source
        knows what the caller could do about it."""
        ...


class AccessPolicy(Protocol):
    """Return None to allow; raise ForbiddenResourceError to deny."""

    async def check(self, product: models.Product, key: str) -> None: ...


class AllowlistAccessPolicy:
    """Allows exactly the keys its source contains for that product."""

    def __init__(self, source: AllowlistSource) -> None:
        self._source = source

    async def check(self, product: models.Product, key: str) -> None:
        if not await self._source.contains(product, key):
            raise ForbiddenResourceError(self._source.denial_message(product, key))


def is_valid_key(product: models.Product, key: str) -> bool:
    return _KEY_PATTERNS[product].match(key) is not None


def parse_key_list(
    value: str, product: models.Product, *, env_var: str
) -> frozenset[str]:
    """Parse a comma-separated key list from settings.

    Whitespace and empty entries are dropped. A wildcard or a malformed key
    is rejected with ValueError rather than silently never matching, so a
    typo is caught at startup. An empty list is allowed; whether that is
    worth a warning depends on the entry point (see warn_if_empty).
    """
    keys = frozenset(key.strip() for key in value.split(",") if key.strip())

    invalid = sorted(key for key in keys if not is_valid_key(product, key))
    if invalid:
        msg = (
            f"{env_var} contains invalid {product.value} keys: {', '.join(invalid)}. "
            "Wildcards are not supported; list each key exactly."
        )
        raise ValueError(msg)

    return keys


_ENV_VARS = {
    models.Product.JIRA: "RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS",
    models.Product.CONFLUENCE: "RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES",
}


def warn_if_empty(source: "StaticAllowlistSource") -> None:
    """On the HTTP server an empty list is usually a variable left empty by
    accident, which locks every user out of that product -- so say so. (On
    stdio, listing only one product is normal; the settings instead require
    at least one list to be non-empty.)"""
    for product, env_var in _ENV_VARS.items():
        if not source.keys_for(product):
            logger.warning(
                "%s has no entries -- every %s key will be denied.",
                env_var,
                product.value,
            )


@dataclasses.dataclass(frozen=True)
class StaticAllowlistSource:
    """A fixed, per-product allowlist from settings
    (RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS /
    RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES). Every caller gets the same
    access. Also read by GET /admin/resource-guard/allowed-spaces so the
    portal shows the values that are actually enforced."""

    jira_projects: frozenset[str]
    confluence_spaces: frozenset[str]

    @classmethod
    def from_csv(cls, jira_csv: str, confluence_csv: str) -> "StaticAllowlistSource":
        source = cls(
            parse_key_list(
                jira_csv,
                models.Product.JIRA,
                env_var="RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS",
            ),
            parse_key_list(
                confluence_csv,
                models.Product.CONFLUENCE,
                env_var="RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES",
            ),
        )
        warn_if_empty(source)
        return source

    def keys_for(self, product: models.Product) -> frozenset[str]:
        if product is models.Product.JIRA:
            return self.jira_projects
        return self.confluence_spaces

    async def contains(self, product: models.Product, key: str) -> bool:
        return key in self.keys_for(product)

    def denial_message(self, product: models.Product, key: str) -> str:
        return (
            f"{key} is not in the configured resource guard allow list "
            f"for {product.value}."
        )
