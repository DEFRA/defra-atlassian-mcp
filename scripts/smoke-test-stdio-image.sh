#!/usr/bin/env bash
# Smoke-test the stdio Docker image the way an MCP client runs it:
# `docker run -i --rm --env-file ...`, JSON-RPC over stdin/stdout.
#
# Checks that the server completes the MCP handshake and lists the expected
# tools, that stdout carries nothing but JSON-RPC, that the image has no
# http-only packages, and that it refuses to start without configuration.
# Makes no calls to Atlassian (the startup check is skipped).
#
# Usage: scripts/smoke-test-stdio-image.sh IMAGE
set -euo pipefail

image="${1:?usage: $0 IMAGE}"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

cat > "$workdir/stdio.env" <<'ENV'
ATLASSIAN_SITE_URL=https://example.atlassian.net
ATLASSIAN_EMAIL=smoke-test@example.com
ATLASSIAN_API_TOKEN=not-a-real-token
RESOURCE_GUARD_ALLOWED_JIRA_PROJECTS=FARM
ATLASSIAN_SKIP_STARTUP_CHECK=true
ENV

echo "== http-only packages are absent"
docker run --rm --entrypoint python "$image" -c "
import importlib.util, sys
present = [m for m in ('fastapi', 'pymongo', 'bson', 'ecs_logging') if importlib.util.find_spec(m)]
sys.exit(f'http-only packages in the stdio image: {present}' if present else 0)
"

echo "== MCP handshake over docker run -i"
{
  printf '%s\n' \
    '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke-test","version":"0"}}}' \
    '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
    '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
  # Keep stdin open long enough for the replies; EOF then stops the server.
  sleep 5
} | docker run -i --rm --env-file "$workdir/stdio.env" "$image" \
    > "$workdir/stdout" 2> "$workdir/stderr"

python3 - "$workdir/stdout" <<'PY'
import json, sys

lines = open(sys.argv[1]).read().splitlines()
messages = []
for line in lines:
    try:
        messages.append(json.loads(line))
    except json.JSONDecodeError:
        sys.exit(f"non-JSON on stdout: {line!r}")
if any(m.get("jsonrpc") != "2.0" for m in messages):
    sys.exit(f"non-JSON-RPC message on stdout: {messages}")

by_id = {m.get("id"): m for m in messages}
if by_id.get(1, {}).get("result", {}).get("serverInfo", {}).get("name") != "atlassian-mcp":
    sys.exit(f"bad initialize response: {by_id.get(1)}")

tools = {t["name"] for t in by_id.get(2, {}).get("result", {}).get("tools", [])}
expected = {
    "search_jira_issues",
    "get_jira_issue",
    "list_confluence_pages",
    "get_confluence_page",
    "list_allowed_keys",
}
if tools != expected:
    sys.exit(f"unexpected tools: {sorted(tools)}")
print(f"ok: {len(lines)} JSON-RPC lines, tools {sorted(tools)}")
PY

if grep -q "not-a-real-token" "$workdir/stderr"; then
  echo "the API token appeared in the server's stderr" >&2
  exit 1
fi

echo "== refuses to start without configuration"
set +e
docker run -i --rm "$image" < /dev/null > "$workdir/stdout" 2> "$workdir/stderr"
exit_code=$?
set -e
if [ "$exit_code" -ne 2 ] || [ -s "$workdir/stdout" ] || ! grep -q "ATLASSIAN_SITE_URL" "$workdir/stderr"; then
  echo "expected exit 2, empty stdout and a config error on stderr; got exit $exit_code" >&2
  cat "$workdir/stderr" >&2
  exit 1
fi
echo "ok: exit 2 with a configuration error on stderr"
