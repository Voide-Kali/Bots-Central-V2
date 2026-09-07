from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "Bots Central V2"
    database_url: str = Field(
        default="postgresql+psycopg://postgres@localhost:5432/bots_central",
        min_length=1,
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    debug: bool = False
    email_verification_hmac_active_key_version: str | None = None
    email_verification_hmac_keys: dict[str, SecretStr] | None = None

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"postgresql", "postgresql+psycopg"} or not parsed.hostname:
            raise ValueError("DATABASE_URL must be a PostgreSQL URL with a host")
        return value

    @field_validator("debug")
    @classmethod
    def prohibit_production_debug(cls, value: bool, info: ValidationInfo) -> bool:
        if info.data.get("app_env") == "production" and value:
            raise ValueError("DEBUG cannot be enabled in production")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
