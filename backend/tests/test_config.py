import base64
import json
import secrets

import pytest
from pydantic import ValidationError

from app.auth.email_verification_materials import (
    EmailVerificationHmacKeyring,
    InvalidEmailVerificationHmacConfiguration,
)
from app.core.config import Settings, get_settings


def test_invalid_database_url_fails_predictably() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL must be a PostgreSQL URL"):
        Settings(database_url="sqlite:///not-allowed.db")


def test_production_debug_is_rejected() -> None:
    with pytest.raises(ValidationError, match="DEBUG cannot be enabled in production"):
        Settings(app_env="production", debug=True)


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
