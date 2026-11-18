import pathlib

import pytest

from app.entrypoints import stdio as entrypoint

_VARS = (
    "ATLASSIAN_SITE_URL",
    "ATLASSIAN_EMAIL",
    "ATLASSIAN_API_TOKEN",
    "ATLASSIAN_API_TOKEN_TYPE",
    "RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS",
    "RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for name in _VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


class TestDefaultEnvFile:
    def test_uses_xdg_config_home(self, tmp_path):
        path = entrypoint.default_env_file(
            {"XDG_CONFIG_HOME": "/xdg"}, windows=False, home=tmp_path
        )

        assert path == pathlib.Path("/xdg/defra-atlassian-mcp/.env")

    def test_falls_back_to_dot_config_in_home(self, tmp_path):
        path = entrypoint.default_env_file({}, windows=False, home=tmp_path)

        assert path == tmp_path / ".config" / "defra-atlassian-mcp" / ".env"

    def test_uses_appdata_on_windows(self, tmp_path):
        path = entrypoint.default_env_file(
            {"APPDATA": "C:/Users/dev/AppData/Roaming", "XDG_CONFIG_HOME": "/xdg"},
            windows=True,
            home=tmp_path,
        )

        assert path == pathlib.Path(
            "C:/Users/dev/AppData/Roaming/defra-atlassian-mcp/.env"
        )


class TestResolveEnvFile:
    def test_an_explicit_file_must_exist(self, tmp_path):
        with pytest.raises(entrypoint.ConfigError, match="does not exist"):
            entrypoint.resolve_env_file(tmp_path / "missing.env", tmp_path / "d.env")

    def test_an_explicit_file_wins_over_the_default(self, tmp_path):
        explicit = tmp_path / "x.env"
        explicit.write_text("")
        default = tmp_path / "d.env"
        default.write_text("")

        assert entrypoint.resolve_env_file(explicit, default) == explicit

    def test_the_default_is_used_only_if_it_exists(self, tmp_path):
        default = tmp_path / "d.env"

        assert entrypoint.resolve_env_file(None, default) is None
        default.write_text("")
        assert entrypoint.resolve_env_file(None, default) == default


class TestLoadSettings:
    def test_names_every_problem_and_shows_an_example(self):
        with pytest.raises(entrypoint.ConfigError) as exc_info:
            entrypoint.load_settings(None)

        message = str(exc_info.value)
        assert "ATLASSIAN_SITE_URL" in message
        assert "ATLASSIAN_EMAIL" in message
        assert "ATLASSIAN_API_TOKEN" in message
        assert "Example configuration" in message

    def test_explains_a_missing_allowlist(self, monkeypatch):
        monkeypatch.setenv("ATLASSIAN_SITE_URL", "https://example.atlassian.net")
        monkeypatch.setenv("ATLASSIAN_EMAIL", "dev@example.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "s3cret-token-value")

        with pytest.raises(entrypoint.ConfigError, match="at least one key"):
            entrypoint.load_settings(None)

    def test_never_echoes_an_input_value(self, monkeypatch):
        """Pydantic errors include the offending input by default; one of
        them could be the token."""
        monkeypatch.setenv("ATLASSIAN_SITE_URL", "https://example.atlassian.net")
        monkeypatch.setenv("ATLASSIAN_EMAIL", "dev@example.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "s3cret-token-value")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN_TYPE", "s3cret-token-value")
        monkeypatch.setenv("RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS", "FARM")

        with pytest.raises(entrypoint.ConfigError) as exc_info:
            entrypoint.load_settings(None)

        assert "s3cret-token-value" not in str(exc_info.value)
        assert "ATLASSIAN_API_TOKEN_TYPE" in str(exc_info.value)


class TestMain:
    def test_a_config_error_exits_2_with_the_message_on_stderr(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            entrypoint.main(["--env-file", "/definitely/not/here.env"])

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "does not exist" in captured.err
