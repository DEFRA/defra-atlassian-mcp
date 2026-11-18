"""Logging for the stdio entry point.

In stdio mode stdout carries the MCP JSON-RPC stream and nothing else, so
every log record must go to stderr. The HTTP entry point keeps its JSON
logging configs (logging.json / logging-dev.json), applied by uvicorn.
"""

import logging
import sys

# Libraries that log every request at INFO. Their lines add noise to the MCP
# client's server log without telling the user anything.
_QUIET_LOGGERS = ("httpx", "httpx2", "httpcore", "mcp.server.lowlevel.server")


def configure_stderr_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(logging.WARNING, root.level))
