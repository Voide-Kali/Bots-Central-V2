import base64
import hashlib
import hmac
import struct
import uuid

import pytest
from pydantic import SecretStr

import app.auth.email_verification_materials as materials
from app.auth.email_verification_materials import (
    EMAIL_VERIFICATION_CODE_HMAC_PROTOCOL,
    EmailVerificationHmacKeyring,
    InvalidEmailVerificationHmacConfiguration,
    InvalidEmailVerificationLinkToken,
    InvalidHumanEmailCode,
    UnknownEmailVerificationHmacKeyVersion,
    decode_link_token,
    digest_external_link_token,
    email_verification_code_digest,
    email_verification_code_hmac_message,
    encode_link_token,
    format_human_email_code,
    generate_human_email_code,
    generate_link_token,
    normalize_human_email_code,
    verify_email_verification_code_digest,
)
from app.core.config import Settings


def test_link_token_generation_is_canonical_and_digests_raw_bytes() -> None:
    first = generate_link_token()
    second = generate_link_token()

    assert len(first.external_token) == 43
    assert "=" not in first.external_token
    assert decode_link_token(first.external_token) == first.raw_token
    assert len(first.raw_token) == 32
    assert len(first.digest) == 32
    assert first.digest == hashlib.sha256(first.raw_token).digest()
    assert digest_external_link_token(first.external_token) == first.digest
    assert first.external_token != second.external_token
    assert first.digest != second.digest
    assert first.external_token not in repr(first)


@pytest.mark.parametrize(
    "token",
    [
        "a" * 43 + "=",
        "a" * 42,
        "a" * 44,
        "a" * 42 + "=",
        "a" * 42 + "+",
        "a" * 42 + "/",
        "a" * 42 + " ",
        "a" * 42 + "\n",
        "a" * 42 + "\t",
        "A" * 42 + "B",
    ],
)
def test_link_token_rejects_noncanonical_public_representations(token: str) -> None:
    with pytest.raises(InvalidEmailVerificationLinkToken):
        decode_link_token(token)


def test_link_token_rejects_non_string() -> None:
    with pytest.raises(TypeError, match="link token must be a string"):
        decode_link_token(None)  # type: ignore[arg-type]


def test_link_token_encoding_requires_exactly_32_bytes() -> None:
    with pytest.raises(materials.EmailVerificationMaterialError):
        encode_link_token(b"short")


def test_human_code_generation_and_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.auth.email_verification_materials.secrets.randbelow", lambda upper: 7)

    code = generate_human_email_code()

    assert code == "00000007"
    assert normalize_human_email_code("12345678") == "12345678"
    assert normalize_human_email_code("1234 5678") == "12345678"
    assert format_human_email_code("12345678") == "1234 5678"
    assert code.isascii() and len(code) == 8 and all("0" <= item <= "9" for item in code)


@pytest.mark.parametrize(
    "code",
    [
        "1234-5678",
        "1234  5678",
        " 12345678",
        "12345678 ",
        "１２３４５６７８",
        "1234567",
        "123456789",
        "abcd5678",
        "1234\t5678",
    ],
)
def test_human_code_rejects_any_unapproved_format(code: str) -> None:
    with pytest.raises(InvalidHumanEmailCode):
        normalize_human_email_code(code)


def test_human_code_requires_string() -> None:
    with pytest.raises(TypeError, match="human email code must be a string"):
        normalize_human_email_code(12345678)  # type: ignore[arg-type]


def test_hmac_framing_and_digest_are_deterministic_and_bound() -> None:
    key = b"k" * 32
    challenge_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    user_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    user_email_id = uuid.UUID("00000000-0000-0000-0000-000000000003")
    message = email_verification_code_hmac_message(
        challenge_id=challenge_id,
        user_id=user_id,
        user_email_id=user_email_id,
        code="1234 5678",
    )
    protocol = EMAIL_VERIFICATION_CODE_HMAC_PROTOCOL.encode("ascii")
    expected_message = b"".join(
        (
            struct.pack(">I", len(protocol)),
            protocol,
            struct.pack(">I", 16),
            challenge_id.bytes,
            struct.pack(">I", len(b"email_verification")),
            b"email_verification",
            struct.pack(">I", 16),
            user_id.bytes,
            struct.pack(">I", 16),
            user_email_id.bytes,
            struct.pack(">I", 8),
            b"12345678",
        )
    )
    digest = email_verification_code_digest(
        key=key,
        challenge_id=challenge_id,
        user_id=user_id,
        user_email_id=user_email_id,
        code="12345678",
    )

    assert message == expected_message
    assert digest == hmac.digest(key, expected_message, "sha256")
    assert len(digest) == 32
    assert digest != email_verification_code_digest(
        key=key,
        challenge_id=uuid.uuid4(),
        user_id=user_id,
        user_email_id=user_email_id,
        code="12345678",
    )
    assert digest != email_verification_code_digest(
        key=key,
        challenge_id=challenge_id,
        user_id=uuid.uuid4(),
        user_email_id=user_email_id,
        code="12345678",
    )
    assert digest != email_verification_code_digest(
        key=key,
        challenge_id=challenge_id,
        user_id=user_id,
        user_email_id=uuid.uuid4(),
        code="12345678",
    )
    assert digest != email_verification_code_digest(
        key=key,
        challenge_id=challenge_id,
        user_id=user_id,
        user_email_id=user_email_id,
        code="87654321",
    )


def test_hmac_verification_uses_constant_time_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    challenge_id, user_id, user_email_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    key = b"k" * 32
    digest = email_verification_code_digest(
        key=key,
        challenge_id=challenge_id,
        user_id=user_id,
        user_email_id=user_email_id,
        code="12345678",
    )
    calls: list[tuple[bytes, bytes]] = []

    def compare_digest(left: bytes, right: bytes) -> bool:
        calls.append((left, right))
        return True

    monkeypatch.setattr(
        "app.auth.email_verification_materials.hmac.compare_digest", compare_digest
    )
    assert verify_email_verification_code_digest(
        expected_digest=digest,
        key=key,
        challenge_id=challenge_id,
        user_id=user_id,
        user_email_id=user_email_id,
        code="12345678",
    )
    assert calls
    assert not verify_email_verification_code_digest(
        expected_digest=b"x",
        key=key,
        challenge_id=challenge_id,
        user_id=user_id,
        user_email_id=user_email_id,
        code="12345678",
    )
    with pytest.raises(InvalidHumanEmailCode):
        verify_email_verification_code_digest(
            expected_digest=digest,
            key=key,
            challenge_id=challenge_id,
            user_id=user_id,
            user_email_id=user_email_id,
            code="invalid",
        )


def encoded_key(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def test_keyring_validates_versions_keys_and_hides_secrets() -> None:
    active_key = b"a" * 32
    old_key = b"b" * 32
    settings = Settings(
        email_verification_hmac_active_key_version="current",
        email_verification_hmac_keys={
            "current": SecretStr(encoded_key(active_key)),
            "previous": SecretStr(encoded_key(old_key)),
        },
    )
    keyring = EmailVerificationHmacKeyring.from_settings(settings)

    assert keyring.active_key_version == "current"
    assert keyring.active_key() == active_key
    assert keyring.key_for_version("previous") == old_key
    assert encoded_key(active_key) not in repr(keyring)
    assert encoded_key(active_key) not in repr(settings)
    with pytest.raises(UnknownEmailVerificationHmacKeyVersion):
        keyring.key_for_version("missing")


@pytest.mark.parametrize(
    "active_version, keys",
    [
        (None, {"current": SecretStr(encoded_key(b"a" * 32))}),
        ("missing", {"current": SecretStr(encoded_key(b"a" * 32))}),
        ("current", {"current": SecretStr(encoded_key(b"short"))}),
        ("current", {"current": SecretStr("not valid!")}),
        ("current", None),
    ],
)
def test_keyring_rejects_unsafe_configuration(
    active_version: str | None, keys: dict[str, SecretStr] | None
) -> None:
    with pytest.raises(InvalidEmailVerificationHmacConfiguration):
        EmailVerificationHmacKeyring(active_key_version=active_version, keys=keys)


@pytest.mark.parametrize(
    "active_version, configured_key",
    [
        ("current", encoded_key(b"short")),
        ("current", "not valid!"),
        ("missing", encoded_key(b"a" * 32)),
    ],
)
def test_keyring_configuration_errors_never_leak_plaintext_secrets(
    active_version: str, configured_key: str
) -> None:
    with pytest.raises(InvalidEmailVerificationHmacConfiguration) as raised:
        EmailVerificationHmacKeyring(
            active_key_version=active_version,
            keys={"current": SecretStr(configured_key)},
        )

    exception = raised.value
    assert configured_key not in str(exception)
    assert configured_key not in repr(exception)
