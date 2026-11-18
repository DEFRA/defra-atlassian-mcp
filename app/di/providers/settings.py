import dishka

from app.config import http as http_config


class SettingsProvider(dishka.Provider):
    @dishka.provide(scope=dishka.Scope.APP)
    def provide_app_config(self) -> http_config.HttpSettings:
        return http_config.HttpSettings()  # type: ignore[call-arg]

    @dishka.provide(scope=dishka.Scope.APP)
    def provide_atlassian_config(
        self, config: http_config.HttpSettings
    ) -> http_config.AtlassianConfig:
        return config.atlassian_config

    @dishka.provide(scope=dishka.Scope.APP)
    def provide_identity_config(
        self, config: http_config.HttpSettings
    ) -> http_config.IdentityConfig:
        return config.identity_config
