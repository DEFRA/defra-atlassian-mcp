import dishka

from app import config as app_config


class SettingsProvider(dishka.Provider):
    @dishka.provide(scope=dishka.Scope.APP)
    def provide_app_config(self) -> app_config.AppConfig:
        return app_config.AppConfig()  # type: ignore[call-arg]

    @dishka.provide(scope=dishka.Scope.APP)
    def provide_atlassian_config(
        self, config: app_config.AppConfig
    ) -> app_config.AtlassianConfig:
        return config.atlassian_config

    @dishka.provide(scope=dishka.Scope.APP)
    def provide_identity_config(
        self, config: app_config.AppConfig
    ) -> app_config.IdentityConfig:
        return config.identity_config
