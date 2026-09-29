import pydantic
import pytest

from app import config as app_config


def _atlassian_config() -> app_config.AtlassianConfig:
    """Built via model_construct so this test never reads real env/.env values."""
    return app_config.AtlassianConfig.model_construct(
        auth_base="https://auth.atlassian.com",
        api_base="https://api.atlassian.com",
        client_id="test-client-id",
        client_secret=pydantic.SecretStr("test-secret"),
        redirect_uri="http://portal.example.com/account/atlassian-linking/callback",
    )


def _make_config(**overrides: object) -> app_config.AppConfig:
    kwargs: dict[str, object] = {
        "BASE_URL": "http://localhost:8085",
        "RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS": "",
        "RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES": "",
        "atlassian_config": _atlassian_config(),
        **overrides,
    }
    return app_config.AppConfig(**kwargs)  # type: ignore[arg-type]


class TestAppConfig:
    def test_no_dev_auth_bypass_fields_remain(self) -> None:
        """Regression guard: the old DEV_AUTH_ENABLED/DEV_AUTH_JWT_SECRET
        bypass mechanism must not come back. See
        tests/unit/auth/test_no_bypass.py for the repo-wide version of this
        check.
        """
        assert "dev_auth_enabled" not in app_config.AppConfig.model_fields
        assert "dev_auth_jwt_secret" not in app_config.AppConfig.model_fields

    def test_server_name_defaults_to_atlassian_mcp(self) -> None:
        cfg = _make_config()

        assert cfg.server_name == "atlassian-mcp"

    def test_the_resource_guard_defaults_to_config_list(self) -> None:
        """config_list is hand-managed CSV config, not the Mongo-backed
        admin-approval workflow -- it can enforce real access control from
        day one without needing real approvals to check against first."""
        cfg = _make_config()

        assert cfg.resource_guard_mode == "config_list"

    def test_an_empty_config_allow_list_is_permitted(self) -> None:
        """Explicitly empty is a valid, deliberate choice (denies that
        product for every space) -- it's an absent var that must fail."""
        cfg = _make_config()

        assert cfg.resource_guard_allowed_jira_projects == ""
        assert cfg.resource_guard_allowed_confluence_spaces == ""

    def test_a_missing_jira_allow_list_var_fails_fast(self) -> None:
        """No default: a deployment that forgets to set this must fail at
        startup, not silently deny (or worse, silently allow) everything."""
        with pytest.raises(pydantic.ValidationError):
            app_config.AppConfig(  # type: ignore[call-arg]
                BASE_URL="http://localhost:8085",
                RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES="",
                atlassian_config=_atlassian_config(),
            )

    def test_a_missing_confluence_allow_list_var_fails_fast(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            app_config.AppConfig(  # type: ignore[call-arg]
                BASE_URL="http://localhost:8085",
                RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS="",
                atlassian_config=_atlassian_config(),
            )


class TestAtlassianConfig:
    def test_defaults(self) -> None:
        cfg = app_config.AtlassianConfig.model_construct(
            client_id="test-client-id",
            client_secret=pydantic.SecretStr("test-secret"),
            redirect_uri="http://portal.example.com/account/atlassian-linking/callback",
        )

        assert cfg.auth_base == "https://auth.atlassian.com"
        assert cfg.api_base == "https://api.atlassian.com"


class TestIdentityConfig:
    def test_defaults(self) -> None:
        cfg = _make_config()

        assert cfg.identity_config.rest_auth_mode == "trusted"
        assert cfg.identity_config.trusted_user_header == "X-User-Id"
        assert cfg.identity_config.default_ttl_days == 90
        assert cfg.identity_config.max_ttl_days == 365

    def test_is_overridable(self) -> None:
        cfg = _make_config(
            identity_config=app_config.IdentityConfig.model_construct(
                rest_auth_mode="token"
            )
        )

        assert cfg.identity_config.rest_auth_mode == "token"
