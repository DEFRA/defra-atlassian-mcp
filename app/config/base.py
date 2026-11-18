"""Settings shared by both entry points.

Kept free of anything HTTP-only (OAuth app credentials, Mongo, the portal),
so app.config.stdio can build on it without the HTTP settings' required
fields. Neither this class nor its subclasses read a cwd-relative .env by
default: the HTTP settings opt in explicitly, and stdio passes the file it
resolved.
"""

from typing import Annotated, Any

import pydantic
import pydantic_settings

from app.integration.atlassian import guard, models

# NoDecode: the env value is a comma-separated string, not JSON, so the
# settings source must hand it to the validator below untouched.
KeyList = Annotated[frozenset[str], pydantic_settings.NoDecode]


class BaseAtlassianSettings(pydantic_settings.BaseSettings):
    # extra="ignore" (not "forbid"): pydantic-settings' env source scans the
    # whole process environment, so "forbid" would hard-fail on any
    # unrelated variable a real deployment or shell sets.
    model_config = pydantic_settings.SettingsConfigDict(extra="ignore")

    request_timeout_seconds: int = pydantic.Field(
        30, alias="REQUEST_TIMEOUT_SECONDS", gt=0
    )
    http_proxy: pydantic.HttpUrl | None = None

    # Required here (no default); a subclass may give them one. Each entry
    # is validated by guard.parse_key_list: no wildcards, no malformed keys,
    # matching is exact and case-sensitive.
    resource_guard_allowed_jira_projects: KeyList = pydantic.Field(
        alias="RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS"
    )
    resource_guard_allowed_confluence_spaces: KeyList = pydantic.Field(
        alias="RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES"
    )

    @pydantic.field_validator("resource_guard_allowed_jira_projects", mode="before")
    @classmethod
    def _parse_jira_projects(cls, value: Any) -> frozenset[str]:
        return _parse(
            value, models.Product.JIRA, "RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS"
        )

    @pydantic.field_validator("resource_guard_allowed_confluence_spaces", mode="before")
    @classmethod
    def _parse_confluence_spaces(cls, value: Any) -> frozenset[str]:
        return _parse(
            value,
            models.Product.CONFLUENCE,
            "RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES",
        )


def _parse(value: Any, product: models.Product, env_var: str) -> frozenset[str]:
    if isinstance(value, str):
        return guard.parse_key_list(value, product, env_var=env_var)
    # Already a collection (constructed in code): validate the same way.
    return guard.parse_key_list(",".join(value), product, env_var=env_var)
