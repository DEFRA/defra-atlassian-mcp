"""Composition root for the stdio entry point.

Deliberately separate from app.di.container, which imports every HTTP
provider (and through them pymongo). This module must never import it.
"""

import dishka

from app.config import stdio as stdio_config
from app.di.providers import stdio as stdio_providers
from app.infra.mcp import dishka_inject


def build_stdio_container(
    settings: stdio_config.StdioSettings,
    *extra_providers: dishka.Provider,
) -> dishka.AsyncContainer:
    """``extra_providers`` lets tests override an edge (the HTTP client)."""
    return dishka.make_async_container(
        stdio_providers.StdioProvider(),
        dishka_inject.FastMCPProvider(),
        *extra_providers,
        context={stdio_config.StdioSettings: settings},
    )
