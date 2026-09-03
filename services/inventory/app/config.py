"""Runtime configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with local-development defaults."""

    app_name: str = "SimplifyNext Inventory Service"
    app_env: str = "development"
    database_url: str = (
        "postgresql+psycopg://simplifynext:simplifynext@localhost:5432/simplifynext"
    )
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings instance."""

    return Settings()
