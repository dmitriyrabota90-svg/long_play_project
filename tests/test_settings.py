from app.config.settings import get_settings


def test_settings_import() -> None:
    settings = get_settings()
    assert settings.app_env
    assert settings.database_url

