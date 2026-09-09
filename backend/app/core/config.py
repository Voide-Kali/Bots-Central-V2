import ipaddress
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse, urlsplit, urlunsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.auth.abuse_control import AbuseControlKey, InvalidAbuseControlConfiguration


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
    email_verification_material_type: Literal["link", "code"] = "link"
    abuse_control_hmac_key: SecretStr | None = None
    trusted_proxy_ip: str | None = None
    public_origin: str | None = None
    argon2_max_concurrency: int = Field(default=2, ge=1, le=16)
    email_verification_delivery_mode: Literal["disabled", "smtp"] = "disabled"
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_sender: str | None = None
    smtp_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

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

    @field_validator("trusted_proxy_ip")
    @classmethod
    def validate_trusted_proxy_ip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return ipaddress.ip_address(value).compressed
        except ValueError as error:
            raise ValueError("TRUSTED_PROXY_IP must be an IP address") from error

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        if self.public_origin is not None:
            self.public_origin = self._normalize_public_origin(self.public_origin)
        if self.app_env == "production" and self.email_verification_delivery_mode != "smtp":
            raise ValueError("EMAIL_VERIFICATION_DELIVERY_MODE must be smtp in production")
        if self.app_env == "production":
            try:
                AbuseControlKey(self.abuse_control_hmac_key)
            except InvalidAbuseControlConfiguration as error:
                raise ValueError(
                    "ABUSE_CONTROL_HMAC_KEY must be a valid key in production"
                ) from error
        if self.email_verification_delivery_mode == "smtp":
            if not self.smtp_host or not self.smtp_sender or self.public_origin is None:
                raise ValueError("SMTP delivery requires SMTP_HOST, SMTP_SENDER, and PUBLIC_ORIGIN")
            if self.smtp_username is not None and self.smtp_password is None:
                raise ValueError("SMTP_PASSWORD is required when SMTP_USERNAME is configured")
        return self

    def _normalize_public_origin(self, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("PUBLIC_ORIGIN must be an absolute HTTP(S) origin")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("PUBLIC_ORIGIN must not contain userinfo")
        if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("PUBLIC_ORIGIN must not contain path, query, or fragment")
        hostname = parsed.hostname
        try:
            parsed_port = parsed.port
        except ValueError as error:
            raise ValueError("PUBLIC_ORIGIN has an invalid port") from error
        is_loopback = hostname == "localhost"
        if not is_loopback:
            try:
                is_loopback = ipaddress.ip_address(hostname).is_loopback
            except ValueError:
                pass
        if self.app_env == "production":
            if parsed.scheme != "https" or is_loopback:
                raise ValueError("PUBLIC_ORIGIN must be non-loopback HTTPS in production")
        elif parsed.scheme == "http" and not is_loopback:
            raise ValueError("HTTP PUBLIC_ORIGIN is allowed only for localhost or loopback")
        netloc = hostname if parsed_port is None else f"{hostname}:{parsed_port}"
        return urlunsplit((parsed.scheme, netloc, "", "", ""))


@lru_cache
def get_settings() -> Settings:
    return Settings()
