"""stdio entry point: ``defra-atlassian-mcp``.

Runs the MCP server over stdin/stdout for a local MCP client (Claude
Desktop, Claude Code, ...), authenticated to Atlassian with the user's own
API token and limited to a configured allowlist.

stdout carries only the MCP JSON-RPC stream. Everything else -- logs,
configuration errors -- goes to stderr.

Configuration is read, highest precedence first, from process environment
variables, then the file given by ``--env-file``, or if no flag is given,
``defra-atlassian-mcp/.env`` in the user config directory if it exists. A
``.env`` in the working directory is never read: the MCP client chooses the
working directory, not the user.
"""

import argparse
import asyncio
import logging
import os
import pathlib
import sys
from collections.abc import Mapping, Sequence

import dishka
import fastmcp
import pydantic

from app.common import stderr_logging
from app.config import stdio as stdio_config
from app.di import stdio_container
from app.infra.mcp import mcp
from app.infra.mcp import tools as atlassian_tools
from app.integration.atlassian import api_token_auth, guard, ports, startup_check
from app.integration.atlassian import client as atlassian_client

logger = logging.getLogger(__name__)

SERVER_NAME = "defra-atlassian-mcp"
_CONFIG_DIR_NAME = "defra-atlassian-mcp"
_EXIT_CONFIG_ERROR = 2
_EXIT_STARTUP_ERROR = 1

_EXAMPLE_ENV = """\
ATLASSIAN_SITE_URL=https://your-site.atlassian.net
ATLASSIAN_EMAIL=you@example.com
ATLASSIAN_API_TOKEN=your-api-token
# ATLASSIAN_API_TOKEN_TYPE=classic   # or scoped
RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS=FARM,AICE
RESOURCE_GUARD_ALLOWED_CONFLUENCE_SPACES=ENG"""


class ConfigError(Exception):
    """The configuration cannot be loaded. The message is for the user."""


def default_env_file(
    environ: Mapping[str, str] | None = None,
    *,
    windows: bool | None = None,
    home: pathlib.Path | None = None,
) -> pathlib.Path:
    """Where the env file lives when --env-file is not given:
    ``%APPDATA%\\defra-atlassian-mcp\\.env`` on Windows, otherwise
    ``$XDG_CONFIG_HOME/defra-atlassian-mcp/.env``, defaulting to
    ``~/.config/defra-atlassian-mcp/.env``."""
    environ = os.environ if environ is None else environ
    windows = (os.name == "nt") if windows is None else windows
    home = pathlib.Path.home() if home is None else home

    if windows and environ.get("APPDATA"):
        base = pathlib.Path(environ["APPDATA"])
    elif environ.get("XDG_CONFIG_HOME"):
        base = pathlib.Path(environ["XDG_CONFIG_HOME"])
    else:
        base = home / ".config"
    return base / _CONFIG_DIR_NAME / ".env"


def resolve_env_file(
    explicit: pathlib.Path | None, default: pathlib.Path
) -> pathlib.Path | None:
    """An explicit --env-file must exist. The default is used only if it
    exists; otherwise configuration comes from the environment alone."""
    if explicit is not None:
        if not explicit.is_file():
            msg = f"--env-file {explicit} does not exist or is not a file."
            raise ConfigError(msg)
        return explicit
    return default if default.is_file() else None


def load_settings(env_file: pathlib.Path | None) -> stdio_config.StdioSettings:
    try:
        return stdio_config.StdioSettings(_env_file=env_file)  # type: ignore[call-arg]
    except pydantic.ValidationError as exc:
        raise ConfigError(_describe(exc, env_file)) from exc


def _describe(exc: pydantic.ValidationError, env_file: pathlib.Path | None) -> str:
    """List what is wrong without echoing any input value -- one of them may
    be the API token."""
    problems = []
    for error in exc.errors(include_input=False, include_url=False):
        field = ".".join(str(part) for part in error["loc"])
        message = error["msg"].removeprefix("Value error, ")
        problems.append(f"  - {field}: {message}" if field else f"  - {message}")

    source = f"environment and {env_file}" if env_file else "environment"
    return (
        f"defra-atlassian-mcp: invalid configuration (read from {source}):\n"
        + "\n".join(problems)
        + "\n\nExample configuration:\n"
        + _EXAMPLE_ENV
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="defra-atlassian-mcp",
        description="Read-only Jira and Confluence MCP server over stdio.",
    )
    parser.add_argument(
        "--env-file",
        type=pathlib.Path,
        default=None,
        help=(
            "Path to a .env file. Defaults to defra-atlassian-mcp/.env in the user "
            "config directory, if present. Environment variables take precedence."
        ),
    )
    return parser.parse_args(argv)


async def serve(settings: stdio_config.StdioSettings) -> None:
    container = stdio_container.build_stdio_container(settings)
    async with container:
        await prepare(container, settings)
        await build(container).run_stdio_async(show_banner=False)


async def prepare(
    container: dishka.AsyncContainer, settings: stdio_config.StdioSettings
) -> None:
    """Resolve credentials (a scoped token's cloud-id lookup happens here)
    and run the startup check unless it is switched off. Raises
    api_token_auth.CloudIdLookupError or startup_check.StartupCheckError."""
    await container.get(ports.AtlassianAuth)
    if settings.skip_startup_check:
        logger.info("Startup check skipped (ATLASSIAN_SKIP_STARTUP_CHECK).")
        return
    await startup_check.run(
        await container.get(atlassian_client.AtlassianClient),
        await container.get(guard.StaticAllowlistSource),
    )


def build(container: dishka.AsyncContainer) -> fastmcp.FastMCP:
    server = mcp.build_server(SERVER_NAME, container)
    atlassian_tools.register_core_tools(server)
    atlassian_tools.register_allowlist_tool(server)
    return server


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)

    try:
        env_file = resolve_env_file(args.env_file, default_env_file())
        settings = load_settings(env_file)
    except ConfigError as exc:
        print(exc, file=sys.stderr)  # logging is not configured yet
        sys.exit(_EXIT_CONFIG_ERROR)

    stderr_logging.configure_stderr_logging(settings.log_level)
    logger.info(
        "Starting defra-atlassian-mcp (stdio) for %s with a %s API token.",
        settings.site_url,
        settings.api_token_type,
    )

    try:
        asyncio.run(serve(settings))
    except (api_token_auth.CloudIdLookupError, startup_check.StartupCheckError) as exc:
        logger.error("%s", exc)
        sys.exit(_EXIT_STARTUP_ERROR)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":  # pragma: no cover
    main()
