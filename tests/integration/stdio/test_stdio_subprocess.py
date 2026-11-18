"""Spawn the real stdio server as a child process and speak raw JSON-RPC to
it. The point is the process boundary: stdout must carry nothing but the MCP
stream (one JSON message per line), and logs and configuration errors must
go to stderr.

The child gets a scrubbed environment and a temporary HOME, so neither the
developer's shell nor their ~/.config/defra-atlassian-mcp/.env can leak in.
"""

import asyncio
import json
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_TIMEOUT = 20


def _env(tmp_path: pathlib.Path, **extra: str) -> dict[str, str]:
    return {
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "PATH": "/usr/bin:/bin",
        "PYTHONUNBUFFERED": "1",
        **extra,
    }


_VALID = {
    "ATLASSIAN_SITE_URL": "https://example.atlassian.net",
    "ATLASSIAN_EMAIL": "dev@example.com",
    "ATLASSIAN_API_TOKEN": "s3cret-token-value",
    "RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS": "FARM",
    # No network in tests: list_tools needs none, and the check would.
    "ATLASSIAN_SKIP_STARTUP_CHECK": "true",
}


async def _spawn(env: dict[str, str], *args: str) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.entrypoints.stdio",
        *args,
        cwd=_REPO_ROOT,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def _send(proc: asyncio.subprocess.Process, message: dict) -> None:
    assert proc.stdin is not None
    proc.stdin.write((json.dumps(message) + "\n").encode())
    await proc.stdin.drain()


async def _receive(proc: asyncio.subprocess.Process, request_id: int) -> dict:
    """Read stdout lines until the response with this id. Every line read
    must be a JSON-RPC message -- anything else is stdout pollution."""
    assert proc.stdout is not None
    while True:
        line = await asyncio.wait_for(proc.stdout.readline(), _TIMEOUT)
        assert line, "server closed stdout before responding"
        message = json.loads(line)
        assert message.get("jsonrpc") == "2.0", line
        if message.get("id") == request_id:
            return message


class TestHandshake:
    async def test_lists_tools_over_stdio_with_a_clean_stdout(self, tmp_path):
        proc = await _spawn(_env(tmp_path, **_VALID))
        try:
            await _send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "smoke-test", "version": "0"},
                    },
                },
            )
            init = await _receive(proc, 1)
            await _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            await _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            listed = await _receive(proc, 2)
        finally:
            assert proc.stdin is not None
            proc.stdin.close()
            remaining_out, err = await asyncio.wait_for(proc.communicate(), _TIMEOUT)

        assert init["result"]["serverInfo"]["name"] == "defra-atlassian-mcp"
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert names == {
            "search_jira_issues",
            "get_jira_issue",
            "list_confluence_pages",
            "get_confluence_page",
            "list_allowed_keys",
        }
        for line in remaining_out.decode().splitlines():
            assert json.loads(line).get("jsonrpc") == "2.0", line
        stderr = err.decode()
        assert "Starting defra-atlassian-mcp (stdio)" in stderr
        assert "s3cret-token-value" not in stderr


class TestStartupFailures:
    async def test_no_allowlist_exits_non_zero_with_the_reason_on_stderr(
        self, tmp_path
    ):
        env = {**_VALID, "RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS": ""}
        proc = await _spawn(_env(tmp_path, **env))

        out, err = await asyncio.wait_for(proc.communicate(), _TIMEOUT)

        assert proc.returncode == 2
        assert out == b""
        assert "at least one key" in err.decode()

    async def test_reads_the_default_env_file_from_the_user_config_dir(self, tmp_path):
        """No --env-file and nothing in the environment: the file under
        $XDG_CONFIG_HOME/defra-atlassian-mcp/ is used. Proven by it supplying a
        bad value that fails validation."""
        config_dir = tmp_path / "config" / "defra-atlassian-mcp"
        config_dir.mkdir(parents=True)
        (config_dir / ".env").write_text(
            "\n".join(f"{k}={v}" for k, v in _VALID.items())
            + "\nATLASSIAN_API_TOKEN_TYPE=bogus\n"
        )
        proc = await _spawn(_env(tmp_path))

        out, err = await asyncio.wait_for(proc.communicate(), _TIMEOUT)

        assert proc.returncode == 2
        assert out == b""
        assert "ATLASSIAN_API_TOKEN_TYPE" in err.decode()

    @pytest.mark.parametrize("args", [("--env-file", "/definitely/not/here.env")])
    async def test_a_missing_env_file_exits_non_zero(self, tmp_path, args):
        proc = await _spawn(_env(tmp_path, **_VALID), *args)

        out, err = await asyncio.wait_for(proc.communicate(), _TIMEOUT)

        assert proc.returncode == 2
        assert out == b""
        assert "does not exist" in err.decode()
