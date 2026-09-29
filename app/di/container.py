import dishka
from dishka.integrations import fastapi as dishka_fastapi

from app.di.providers import (
    auth,
    identity,
    infrastructure,
    integration,
    request_scope,
    settings,
)
from app.infra.mcp import dishka_inject


def build_sync_container() -> dishka.Container:
    return dishka.make_container(settings.SettingsProvider())


def build_async_container() -> dishka.AsyncContainer:
    return dishka.make_async_container(
        settings.SettingsProvider(),
        infrastructure.InfrastructureProvider(),
        identity.IdentityProvider(),
        auth.AuthProvider(),
        integration.AtlassianProvider(),
        request_scope.RequestScopeProvider(),
        dishka_fastapi.FastapiProvider(),
        dishka_inject.FastMCPProvider(),
    )
