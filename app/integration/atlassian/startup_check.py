"""Startup check for the stdio entry point.

Two tiers:

- Bad credentials are fatal. A 401 from the "who am I" endpoint is never
  recoverable by waiting, so the server stops with a clear message rather
  than starting and failing every tool call.
- Everything else is a warning. A listed key that does not resolve is
  probably a typo and should be visible, but a transient outage, a missing
  read-user scope (403) or a permission the user gains later must not stop
  the server.

Warnings go to the log (stderr in stdio mode).
"""

import logging

from app.integration.atlassian import client as atlassian_client
from app.integration.atlassian import errors, guard, models

logger = logging.getLogger(__name__)


class StartupCheckError(Exception):
    """Fatal: the server should not start. The message is for the user."""


_REJECTED_MESSAGE = (
    "Atlassian rejected the credentials (HTTP 401). Check ATLASSIAN_EMAIL and "
    "ATLASSIAN_API_TOKEN, and that ATLASSIAN_API_TOKEN_TYPE matches the token "
    "(classic or scoped)."
)


async def run(
    client: atlassian_client.AtlassianClient,
    allowlist: guard.StaticAllowlistSource,
) -> None:
    await _check_credentials(client, allowlist)
    for key in sorted(allowlist.jira_projects):
        await _probe(client, models.Product.JIRA, key, f"/rest/api/3/project/{key}")
    for key in sorted(allowlist.confluence_spaces):
        await _probe_space(client, key)


async def _check_credentials(
    client: atlassian_client.AtlassianClient,
    allowlist: guard.StaticAllowlistSource,
) -> None:
    # Ask the product the user actually listed keys for: a Confluence-only
    # user may have no Jira licence.
    if allowlist.jira_projects:
        product, path = models.Product.JIRA, "/rest/api/3/myself"
    else:
        product, path = models.Product.CONFLUENCE, "/wiki/rest/api/user/current"

    try:
        await client.get(product, path)
    except errors.AtlassianApiError as exc:
        if exc.status_code == 401:
            raise StartupCheckError(_REJECTED_MESSAGE) from exc
        logger.warning(
            "Credential check against %s returned HTTP %s; continuing.",
            product.value,
            exc.status_code,
        )
    except errors.AtlassianUnavailableError:
        logger.warning("Atlassian is unreachable; continuing without a startup check.")


async def _probe(
    client: atlassian_client.AtlassianClient,
    product: models.Product,
    key: str,
    path: str,
) -> None:
    try:
        await client.get(product, path)
    except errors.AtlassianApiError as exc:
        logger.warning(
            "Allowlisted %s key %s did not resolve (HTTP %s) -- check for a typo "
            "or missing permission.",
            product.value,
            key,
            exc.status_code,
        )
    except errors.AtlassianUnavailableError:
        logger.warning(
            "Could not check %s key %s: Atlassian is unreachable.", product.value, key
        )


async def _probe_space(client: atlassian_client.AtlassianClient, key: str) -> None:
    product = models.Product.CONFLUENCE
    try:
        payload = await client.get(
            product, "/wiki/api/v2/spaces", params={"keys": key, "limit": 1}
        )
    except errors.AtlassianApiError as exc:
        logger.warning(
            "Could not check confluence key %s (HTTP %s).", key, exc.status_code
        )
        return
    except errors.AtlassianUnavailableError:
        logger.warning(
            "Could not check confluence key %s: Atlassian is unreachable.", key
        )
        return

    if not payload.get("results"):
        logger.warning(
            "Allowlisted confluence key %s did not resolve -- check for a typo "
            "or missing permission.",
            key,
        )
