"""StdioSettings: the stdio server's only configuration. It must refuse to
start without credentials or an allowlist, never read a cwd-relative .env,
and never render the API token."""

import pathlib

import pydantic
import pytest

from app.config import stdio as stdio_config

_REQUIRED_ENV = {
    "ATLASSIAN_SITE_URL": "https://example.atlassian.net",
    "ATLASSIAN_EMAIL": "dev@example.com",
    "ATLASSIAN_API_TOKEN": "s3cret-token-value",
    "RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS": "FARM",
}
_ALL_VARS = (
    *_REQUIRED_ENV,
    "RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES",
    "ATLASSIAN_API_TOKEN_TYPE",
    "ATLASSIAN_SKIP_STARTUP_CHECK",
    "LOG_LEVEL",
    "REQUEST_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    """Isolate from the developer's shell and from any .env in the repo:
    run from an empty directory with none of the variables set."""
    for name in _ALL_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def _set(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for name, value in {**_REQUIRED_ENV, **overrides}.items():
        monkeypatch.setenv(name, value)


class TestRequired:
    def test_builds_from_the_environment(self, monkeypatch):
        _set(monkeypatch)

        settings = stdio_config.StdioSettings()  # type: ignore[call-arg]

        assert str(settings.site_url) == "https://example.atlassian.net/"
        assert settings.email == "dev@example.com"
        assert settings.api_token.get_secret_value() == "s3cret-token-value"
        assert settings.api_token_type == "classic"
        assert settings.skip_startup_check is False
        assert settings.resource_guard_allowed_jira_projects == frozenset({"FARM"})
        assert settings.resource_guard_allowed_confluence_spaces == frozenset()

    @pytest.mark.parametrize(
        "missing", ["ATLASSIAN_SITE_URL", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN"]
    )
    def test_refuses_to_start_without_credentials(self, monkeypatch, missing):
        _set(monkeypatch)
        monkeypatch.delenv(missing)

        with pytest.raises(pydantic.ValidationError, match=missing):
            stdio_config.StdioSettings()  # type: ignore[call-arg]

    def test_refuses_a_blank_token(self, monkeypatch):
        _set(monkeypatch, ATLASSIAN_API_TOKEN="   ")

        with pytest.raises(pydantic.ValidationError):
            stdio_config.StdioSettings()  # type: ignore[call-arg]

    def test_refuses_to_start_with_no_allowlist(self, monkeypatch):
        _set(monkeypatch, RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS="")

        with pytest.raises(pydantic.ValidationError, match="at least one key"):
            stdio_config.StdioSettings()  # type: ignore[call-arg]

    def test_a_confluence_only_allowlist_is_enough(self, monkeypatch):
        _set(
            monkeypatch,
            RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS="",
            RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES="ENG",
        )

        settings = stdio_config.StdioSettings()  # type: ignore[call-arg]

        assert settings.resource_guard_allowed_confluence_spaces == frozenset({"ENG"})

    @pytest.mark.parametrize("value", ["*", "farm", "FARM,*", "FARM-1"])
    def test_rejects_wildcards_and_malformed_keys(self, monkeypatch, value):
        _set(monkeypatch, RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS=value)

        with pytest.raises(pydantic.ValidationError):
            stdio_config.StdioSettings()  # type: ignore[call-arg]

    def test_rejects_an_unknown_token_type(self, monkeypatch):
        _set(monkeypatch, ATLASSIAN_API_TOKEN_TYPE="oauth")

        with pytest.raises(pydantic.ValidationError):
            stdio_config.StdioSettings()  # type: ignore[call-arg]

    def test_accepts_a_scoped_token_type(self, monkeypatch):
        _set(monkeypatch, ATLASSIAN_API_TOKEN_TYPE="scoped")

        settings = stdio_config.StdioSettings()  # type: ignore[call-arg]

        assert settings.api_token_type == "scoped"


class TestEnvFile:
    def test_does_not_read_a_dotenv_in_the_working_directory(self, tmp_path):
        """An MCP client launches the server from an arbitrary directory, so
        a stray .env there must not be picked up."""
        (tmp_path / ".env").write_text(
            "\n".join(f"{k}={v}" for k, v in _REQUIRED_ENV.items())
        )

        with pytest.raises(pydantic.ValidationError):
            stdio_config.StdioSettings()  # type: ignore[call-arg]

    def test_reads_the_env_file_it_is_given(self, tmp_path):
        env_file = tmp_path / "atlassian-mcp.env"
        env_file.write_text("\n".join(f"{k}={v}" for k, v in _REQUIRED_ENV.items()))

        settings = stdio_config.StdioSettings(_env_file=env_file)  # type: ignore[call-arg]

        assert settings.email == "dev@example.com"

    def test_process_environment_beats_the_env_file(self, monkeypatch, tmp_path):
        env_file = tmp_path / "atlassian-mcp.env"
        env_file.write_text("\n".join(f"{k}={v}" for k, v in _REQUIRED_ENV.items()))
        monkeypatch.setenv("ATLASSIAN_EMAIL", "override@example.com")

        settings = stdio_config.StdioSettings(_env_file=env_file)  # type: ignore[call-arg]

        assert settings.email == "override@example.com"


class TestSecrecy:
    def test_the_token_is_not_in_repr_or_str(self, monkeypatch):
        _set(monkeypatch)

        settings = stdio_config.StdioSettings()  # type: ignore[call-arg]

        assert "s3cret-token-value" not in repr(settings)
        assert "s3cret-token-value" not in str(settings)

    def test_the_token_is_not_in_a_validation_error(self, monkeypatch):
        _set(monkeypatch, ATLASSIAN_SITE_URL="not a url")

        with pytest.raises(pydantic.ValidationError) as exc_info:
            stdio_config.StdioSettings()  # type: ignore[call-arg]

        assert "s3cret-token-value" not in str(exc_info.value)
