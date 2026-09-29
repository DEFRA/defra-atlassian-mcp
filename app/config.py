import pydantic
import pydantic_settings


class AtlassianConfig(pydantic_settings.BaseSettings):
    """Atlassian OAuth 2.0 (3LO) and API settings.

    Atlassian splits the authorize and API hosts: ``auth_base`` serves the
    authorize/token endpoints, while ``api_base`` serves the product APIs
    under ``/ex/{jira,confluence}/{cloud_id}``. The cloud id is not
    configuration — it is resolved per user from
    ``/oauth/token/accessible-resources`` at link time and stored on the
    token (see app/integration/linking/models.py).
    """

    model_config = pydantic_settings.SettingsConfigDict(env_file=".env", extra="ignore")
    auth_base: str = pydantic.Field(
        "https://auth.atlassian.com", alias="ATLASSIAN_AUTH_BASE"
    )
    api_base: str = pydantic.Field(
        "https://api.atlassian.com", alias="ATLASSIAN_API_BASE"
    )
    client_id: str = pydantic.Field(..., alias="ATLASSIAN_CLIENT_ID")
    client_secret: pydantic.SecretStr = pydantic.Field(
        ..., alias="ATLASSIAN_CLIENT_SECRET"
    )
    # Absolute URL, and it belongs to the *portal*, not this server: Atlassian
    # redirects the browser to the portal's callback page, which then forwards
    # the code and state to GET /linking/callback here. It must match the
    # callback URL registered on the Atlassian OAuth app exactly.
    redirect_uri: str = pydantic.Field(..., alias="ATLASSIAN_REDIRECT_URI")


class IdentityConfig(pydantic_settings.BaseSettings):
    """Personal-access-token identity: how this server verifies its own
    minted tokens and mints new ones. See app/identity/ and
    app/infra/rest/token_router.py.
    """

    model_config = pydantic_settings.SettingsConfigDict(env_file=".env", extra="ignore")

    rest_auth_mode: str = pydantic.Field("trusted", alias="REST_AUTH_MODE")
    trusted_user_header: str = pydantic.Field("X-User-Id", alias="TRUSTED_USER_HEADER")

    default_ttl_days: int = pydantic.Field(90, alias="IDENTITY_DEFAULT_TTL_DAYS")
    max_ttl_days: int = pydantic.Field(365, alias="IDENTITY_MAX_TTL_DAYS")
    last_used_throttle_seconds: int = pydantic.Field(
        300, alias="IDENTITY_LAST_USED_THROTTLE_SECONDS"
    )


class AppConfig(pydantic_settings.BaseSettings):
    # extra="ignore" (not "forbid"): pydantic-settings' env source scans the whole
    # process environment, not just this model's declared fields, so "forbid" would
    # hard-fail on any unrelated var a real deployment sets (AWS_*, OTEL_*, ...).
    model_config = pydantic_settings.SettingsConfigDict(env_file=".env", extra="ignore")
    python_env: str | None = None
    host: str = "127.0.0.1"
    port: int = 8085
    log_config: str | None = None
    mongo_uri: str | None = None
    mongo_truststore: str = "TRUSTSTORE_CDP_ROOT_CA"
    aws_endpoint_url: str | None = None
    http_proxy: pydantic.HttpUrl | None = None
    tracing_header: str = "x-cdp-request-id"
    base_url: pydantic.HttpUrl = pydantic.Field(..., alias="BASE_URL")
    server_name: str = pydantic.Field("atlassian-mcp", alias="SERVER_NAME")

    # "config_list" (default) — the services deny access unless the space
    # key is listed, per product, in RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS /
    # RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES. This list is hand-managed
    # config, entirely outside the admin portal's approval workflow. Both
    # vars are required (no default) so a deployment fails fast at startup
    # if it forgets to set them, rather than silently denying everything --
    # an empty value is fine and denies that product, but the var must be
    # present. A present-but-empty var logs a warning. "allow_list" — the
    # services deny access unless an approved SpaceAccessRequest exists for
    # the (user, space, product) triple. Flip to it only once the admin
    # review workflow has real approvals to check against — flipping first
    # denies all traffic. "allow_all" — every request succeeds; the
    # governance workflow (app/integration/atlassian/) still records requests
    # and decisions but nothing is enforced.
    resource_guard_mode: str = pydantic.Field(
        "config_list", alias="RESOURCE_GUARD_MODE"
    )
    resource_guard_allowed_jira_projects: str = pydantic.Field(
        ..., alias="RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS"
    )
    resource_guard_allowed_confluence_spaces: str = pydantic.Field(
        ..., alias="RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES"
    )

    atlassian_config: AtlassianConfig = pydantic.Field(default_factory=AtlassianConfig)  # type: ignore
    identity_config: IdentityConfig = pydantic.Field(default_factory=IdentityConfig)  # type: ignore
