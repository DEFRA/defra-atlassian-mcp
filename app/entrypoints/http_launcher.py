"""Console-script target for ``atlassian-mcp-http``.

Console scripts are installed whatever extras are chosen, so
``atlassian-mcp-http`` exists in a core-only install too, where
app.entrypoints.http cannot even be imported (it imports fastapi at module
level). This launcher imports it lazily and turns a missing http-only
package into a clear instruction instead of a traceback.
"""

import importlib
import sys

_HTTP_ONLY_PACKAGES = frozenset(
    {"fastapi", "uvicorn", "pymongo", "bson", "ecs_logging", "asgi_logger"}
)


def main() -> None:
    try:
        http = importlib.import_module("app.entrypoints.http")
    except ModuleNotFoundError as exc:
        missing = (exc.name or "").split(".")[0]
        if missing not in _HTTP_ONLY_PACKAGES:
            raise
        print(  # logging is not configured yet
            f"atlassian-mcp-http: {missing} is not installed. The HTTP server "
            "needs the 'http' extra, e.g. `uv sync --extra http` or "
            "`pip install 'atlassian-mcp[http]'`. For the local stdio server, "
            "run `atlassian-mcp` instead.",
            file=sys.stderr,
        )
        sys.exit(1)
    http.main()
