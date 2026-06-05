from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All application datetimes must be stored in UTC. The scheduler timezone is
    separate so operators can choose a wall-clock schedule for jobs.
    """

    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    database_url: str = Field(
        default="postgresql+psycopg2://collector:collector_password@postgres:5432/commodity_dataset",
        alias="DATABASE_URL",
    )
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
    raw_data_dir: Path = Field(default=Path("data/raw"), alias="RAW_DATA_DIR")
    export_data_dir: Path = Field(default=Path("data/exports"), alias="EXPORT_DATA_DIR")
    schedule_timezone: str = Field(default="Europe/Moscow", alias="SCHEDULE_TIMEZONE")
    current_price_scheduler_enabled: bool = Field(default=False, alias="CURRENT_PRICE_SCHEDULER_ENABLED")
    current_price_schedule_times: str = Field(default="09:00,18:00", alias="CURRENT_PRICE_SCHEDULE_TIMES")
    current_price_test_interval_seconds: int | None = Field(default=None, alias="CURRENT_PRICE_TEST_INTERVAL_SECONDS")
    cbr_fx_scheduler_enabled: bool = Field(default=False, alias="CBR_FX_SCHEDULER_ENABLED")
    cbr_fx_schedule_time: str = Field(default="10:00", alias="CBR_FX_SCHEDULE_TIME")
    feature_builder_scheduler_enabled: bool = Field(default=False, alias="FEATURE_BUILDER_SCHEDULER_ENABLED")
    feature_builder_schedule_time: str = Field(default="19:30", alias="FEATURE_BUILDER_SCHEDULE_TIME")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    log_dir: Path = Field(default=Path("logs"), alias="LOG_DIR")
    log_max_bytes: int = Field(default=10_485_760, alias="LOG_MAX_BYTES")
    log_backup_count: int = Field(default=10, alias="LOG_BACKUP_COUNT")

    @field_validator("current_price_test_interval_seconds", mode="before")
    @classmethod
    def empty_interval_is_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
