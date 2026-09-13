import base64
import json
import secrets
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.auth.email_verification_materials import (
    EmailVerificationHmacKeyring,
    InvalidEmailVerificationHmacConfiguration,
)
from app.core.config import Settings, get_settings


def abuse_control_secret() -> SecretStr:
    return SecretStr(base64.urlsafe_b64encode(b"b" * 32).decode("ascii").rstrip("="))


def test_invalid_database_url_fails_predictably() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL must be a PostgreSQL URL"):
        Settings(database_url="sqlite:///not-allowed.db")


def test_production_debug_is_rejected() -> None:
    with pytest.raises(ValidationError, match="DEBUG cannot be enabled in production"):
        Settings(app_env="production", debug=True)


def test_public_origin_is_normalized_and_rejects_unsafe_production_values() -> None:
    settings = Settings(public_origin="http://localhost:8000/")
    assert settings.public_origin == "http://localhost:8000"
    with pytest.raises(ValidationError, match="PUBLIC_ORIGIN must be non-loopback HTTPS"):
        Settings(app_env="production", public_origin="http://localhost:8000")
    with pytest.raises(ValidationError, match="PUBLIC_ORIGIN must not contain path"):
        Settings(public_origin="https://example.com/verification")


def test_smtp_mode_requires_server_config_and_public_origin() -> None:
    with pytest.raises(ValidationError, match="SMTP delivery requires"):
        Settings(email_verification_delivery_mode="smtp")


def test_smtp_ca_file_rejects_empty_or_unloadable_value(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="SMTP_CA_FILE must not be empty"):
        Settings(smtp_ca_file="  ")

    sentinel = tmp_path / "CA-MATERIAL-MUST-NOT-LEAK"
    with pytest.raises(
        ValidationError, match="SMTP_CA_FILE must name a readable regular file"
    ) as raised:
        Settings(smtp_ca_file=sentinel)

    assert "CA-MATERIAL-MUST-NOT-LEAK" not in str(raised.value)
    assert "CA-MATERIAL-MUST-NOT-LEAK" not in repr(raised.value)

    invalid_pem = tmp_path / "invalid.pem"
    invalid_pem.write_text("CA-MATERIAL-MUST-NOT-LEAK", encoding="ascii")
    with pytest.raises(ValidationError, match="SMTP_CA_FILE could not be loaded") as raised:
        Settings(smtp_ca_file=invalid_pem)

    assert "CA-MATERIAL-MUST-NOT-LEAK" not in str(raised.value)
    assert "CA-MATERIAL-MUST-NOT-LEAK" not in repr(raised.value)


@pytest.mark.parametrize("app_env", ["development", "test"])
def test_non_production_allows_disabled_email_delivery(app_env: str) -> None:
    settings = Settings(app_env=app_env)

    assert settings.email_verification_delivery_mode == "disabled"


def test_production_requires_smtp_email_delivery() -> None:
    with pytest.raises(ValidationError, match="EMAIL_VERIFICATION_DELIVERY_MODE must be smtp"):
        Settings(app_env="production")


def test_production_rejects_incomplete_smtp_delivery() -> None:
    with pytest.raises(ValidationError, match="SMTP delivery requires"):
        Settings(
            app_env="production",
            email_verification_delivery_mode="smtp",
            public_origin="https://verify.example.com",
            abuse_control_hmac_key=abuse_control_secret(),
        )


def test_production_requires_a_valid_separate_abuse_control_secret() -> None:
    base_settings: dict[str, Any] = {
        "app_env": "production",
        "email_verification_delivery_mode": "smtp",
        "public_origin": "https://verify.example.com",
        "smtp_host": "smtp.example.com",
        "smtp_sender": "verification@example.com",
    }
    with pytest.raises(ValidationError, match="ABUSE_CONTROL_HMAC_KEY must be a valid key"):
        Settings(**base_settings)
    with pytest.raises(ValidationError, match="ABUSE_CONTROL_HMAC_KEY must be a valid key"):
        Settings(**base_settings, abuse_control_hmac_key=SecretStr("invalid"))


def test_production_accepts_complete_smtp_delivery_with_https_public_origin() -> None:
    settings = Settings(
        app_env="production",
        email_verification_delivery_mode="smtp",
        public_origin="https://verify.example.com",
        smtp_host="smtp.example.com",
        smtp_sender="verification@example.com",
        abuse_control_hmac_key=abuse_control_secret(),
    )

    assert settings.email_verification_delivery_mode == "smtp"
    assert settings.public_origin == "https://verify.example.com"


def test_docker_entrypoint_disables_uvicorn_proxy_header_parsing() -> None:
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text(encoding="utf-8")

    assert '"--no-proxy-headers"' in dockerfile


def test_email_verification_keyring_loads_json_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_key = secrets.token_bytes(32)
    previous_key = secrets.token_bytes(32)
    active_encoded = base64.urlsafe_b64encode(active_key).decode("ascii").rstrip("=")
    previous_encoded = base64.urlsafe_b64encode(previous_key).decode("ascii").rstrip("=")
    monkeypatch.setenv("EMAIL_VERIFICATION_HMAC_ACTIVE_KEY_VERSION", "current")
    monkeypatch.setenv(
        "EMAIL_VERIFICATION_HMAC_KEYS",
        json.dumps({"current": active_encoded, "previous": previous_encoded}),
    )
    get_settings.cache_clear()

    settings = Settings()
    keyring = EmailVerificationHmacKeyring.from_settings(settings)

    assert settings.email_verification_hmac_active_key_version == "current"
    assert settings.email_verification_hmac_keys is not None
    assert settings.email_verification_hmac_keys["current"].get_secret_value() == active_encoded
    assert keyring.active_key_version == "current"
    assert keyring.active_key() == active_key
    assert keyring.key_for_version("previous") == previous_key
    assert active_encoded not in repr(settings)
    assert previous_encoded not in repr(settings)
    assert active_encoded not in repr(keyring)
    assert previous_encoded not in repr(keyring)
    get_settings.cache_clear()


def test_email_verification_settings_are_optional_but_keyring_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EMAIL_VERIFICATION_HMAC_ACTIVE_KEY_VERSION", raising=False)
    monkeypatch.delenv("EMAIL_VERIFICATION_HMAC_KEYS", raising=False)
    get_settings.cache_clear()

    settings = Settings()

    assert settings.email_verification_hmac_active_key_version is None
    assert settings.email_verification_hmac_keys is None
    with pytest.raises(InvalidEmailVerificationHmacConfiguration):
        EmailVerificationHmacKeyring.from_settings(settings)
    get_settings.cache_clear()


def test_invalid_email_verification_keyring_environment_never_leaks_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "THIS-MUST-NEVER-APPEAR-IN-ERRORS"
    monkeypatch.setenv("EMAIL_VERIFICATION_HMAC_KEYS", json.dumps([sentinel]))
    get_settings.cache_clear()

    with pytest.raises(ValidationError) as raised:
        Settings()

    exception = raised.value
    assert sentinel not in str(exception)
    assert sentinel not in repr(exception)
    get_settings.cache_clear()


def test_malformed_email_verification_keyring_json_never_leaks_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "THIS-MUST-NEVER-APPEAR-IN-ERRORS"
    monkeypatch.setenv("EMAIL_VERIFICATION_HMAC_KEYS", f'{{"current":"{sentinel}",')
    get_settings.cache_clear()

    with pytest.raises(ValidationError) as raised:
        Settings()

    exception = raised.value
    assert sentinel not in str(exception)
    assert sentinel not in repr(exception)
    for related_exception in (exception.__cause__, exception.__context__):
        if related_exception is not None:
            assert sentinel not in str(related_exception)
            assert sentinel not in repr(related_exception)
    get_settings.cache_clear()
