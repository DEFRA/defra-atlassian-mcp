"""Settings for the stdio entry point: one user's API token and a fixed
allowlist.

No env_file is configured here. The entry point resolves the file itself
(--env-file, else the user config directory) and passes it as
``StdioSettings(_env_file=path)``, so a cwd-relative .env is never read --
an MCP client launches the server from an arbitrary directory. Process
environment variables take precedence over the file.
"""

from typing import Literal, Self

import pydantic

from app.config import base


class StdioSettings(base.BaseAtlassianSettings):
    site_url: pydantic.HttpUrl = pydantic.Field(alias="ATLASSIAN_SITE_URL")
    email: str = pydantic.Field(alias="ATLASSIAN_EMAIL", min_length=3)
    api_token: pydantic.SecretStr = pydantic.Field(alias="ATLASSIAN_API_TOKEN")
    # "classic": basic auth against the site URL. "scoped": basic auth
    # against Atlassian's API gateway, addressed by the site's cloud id,
    # which is looked up from the site URL at startup.
    api_token_type: Literal["classic", "scoped"] = pydantic.Field(
        "classic", alias="ATLASSIAN_API_TOKEN_TYPE"
    )
    skip_startup_check: bool = pydantic.Field(
        False, alias="ATLASSIAN_SKIP_STARTUP_CHECK"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = pydantic.Field(
        "INFO", alias="LOG_LEVEL"
    )

    # Optional individually (a user may only need one product), but at
    # least one must list something -- see _require_an_allowlist.
    resource_guard_allowed_jira_projects: base.KeyList = pydantic.Field(
        frozenset(), alias="RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS"
    )
    resource_guard_allowed_confluence_spaces: base.KeyList = pydantic.Field(
        frozenset(), alias="RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES"
    )

    @pydantic.field_validator("api_token")
    @classmethod
    def _token_not_blank(cls, value: pydantic.SecretStr) -> pydantic.SecretStr:
        if not value.get_secret_value().strip():
            msg = "ATLASSIAN_API_TOKEN is empty."
            raise ValueError(msg)
        return value

    @pydantic.model_validator(mode="after")
    def _require_an_allowlist(self) -> Self:
        if not (
            self.resource_guard_allowed_jira_projects
            or self.resource_guard_allowed_confluence_spaces
        ):
            msg = (
                "Set RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS and/or "
                "RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES to at least one key. "
                "The stdio server will not start with nothing allowed."
            )
            raise ValueError(msg)
        return self
