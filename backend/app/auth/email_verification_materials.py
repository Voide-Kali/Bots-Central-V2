"""Cryptographic material primitives for email-verification challenges.

This module deliberately does not issue, resend, consume, or persist challenges.
It only constructs and validates the material required by those future flows.
"""

import base64
import hashlib
import hmac
import re
import secrets
import struct
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from pydantic import SecretStr

LINK_TOKEN_BYTE_LENGTH = 32
LINK_TOKEN_EXTERNAL_LENGTH = 43
HUMAN_EMAIL_CODE_LENGTH = 8
HUMAN_EMAIL_CODE_MAXIMUM = 100_000_000
HMAC_DIGEST_LENGTH = 32
HMAC_KEY_MINIMUM_BYTES = 32
EMAIL_VERIFICATION_CODE_HMAC_PROTOCOL = "bots-central.email-verification-code-hmac.v1"
EMAIL_VERIFICATION_CODE_HMAC_PURPOSE = "email_verification"

_BASE64URL_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_HUMAN_CODE_PATTERN = re.compile(r"^[0-9]{8}$")
_HUMAN_CODE_DISPLAY_PATTERN = re.compile(r"^[0-9]{4} [0-9]{4}$")


class EmailVerificationMaterialError(ValueError):
    """Raised when public challenge material is malformed."""


class InvalidEmailVerificationLinkToken(EmailVerificationMaterialError):
    """Raised when a link token does not have the canonical external format."""


class InvalidHumanEmailCode(EmailVerificationMaterialError):
    """Raised when a human verification code is not in an accepted format."""


class InvalidEmailVerificationHmacConfiguration(ValueError):
    """Raised when the externally supplied email-verification keyring is unsafe."""


class UnknownEmailVerificationHmacKeyVersion(LookupError):
    """Raised when a challenge refers to a key version not in the keyring."""


@dataclass(frozen=True)
class LinkTokenMaterial:
    """Fresh link-token material whose plaintext must remain in memory only."""

    raw_token: bytes = field(repr=False)
    external_token: str = field(repr=False)
    digest: bytes = field(repr=False)


def _require_bytes(value: bytes, *, name: str) -> bytes:
    if not isinstance(value, bytes):
        raise TypeError(f"{name} must be bytes")
    return value


def _base64url_decode_canonical(
    value: str, *, error_type: type[EmailVerificationMaterialError]
) -> bytes:
    if not isinstance(value, str):
        raise TypeError("link token must be a string")
    if len(value) != LINK_TOKEN_EXTERNAL_LENGTH or not _BASE64URL_TOKEN_PATTERN.fullmatch(value):
        raise error_type("email verification link token is invalid")
    try:
        decoded = base64.urlsafe_b64decode(f"{value}=")
    except (ValueError, UnicodeEncodeError) as error:
        raise error_type("email verification link token is invalid") from error
    if len(decoded) != LINK_TOKEN_BYTE_LENGTH:
        raise error_type("email verification link token is invalid")
    encoded = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if encoded != value:
        raise error_type("email verification link token is invalid")
    return decoded


def encode_link_token(raw_token: bytes) -> str:
    """Encode exactly 32 token bytes as canonical unpadded base64url."""
    raw_token = _require_bytes(raw_token, name="raw link token")
    if len(raw_token) != LINK_TOKEN_BYTE_LENGTH:
        raise EmailVerificationMaterialError("raw link token must be exactly 32 bytes")
    return base64.urlsafe_b64encode(raw_token).decode("ascii").rstrip("=")


def decode_link_token(external_token: str) -> bytes:
    """Strictly decode the only accepted public representation of a link token."""
    return _base64url_decode_canonical(
        external_token, error_type=InvalidEmailVerificationLinkToken
    )


def link_token_digest(raw_token: bytes) -> bytes:
    """Return the SHA-256 digest of the original 32 token bytes."""
    raw_token = _require_bytes(raw_token, name="raw link token")
    if len(raw_token) != LINK_TOKEN_BYTE_LENGTH:
        raise EmailVerificationMaterialError("raw link token must be exactly 32 bytes")
    return hashlib.sha256(raw_token).digest()


def digest_external_link_token(external_token: str) -> bytes:
    """Decode a canonical public token then digest its bytes, never its text."""
    return link_token_digest(decode_link_token(external_token))


def generate_link_token() -> LinkTokenMaterial:
    """Generate fresh in-memory link material using the operating-system CSPRNG."""
    raw_token = secrets.token_bytes(LINK_TOKEN_BYTE_LENGTH)
    return LinkTokenMaterial(
        raw_token=raw_token,
        external_token=encode_link_token(raw_token),
        digest=link_token_digest(raw_token),
    )


def generate_human_email_code() -> str:
    """Generate an eight-digit ASCII code, retaining leading zeroes."""
    return f"{secrets.randbelow(HUMAN_EMAIL_CODE_MAXIMUM):08d}"


def normalize_human_email_code(code: str) -> str:
    """Accept only raw eight digits or the single approved presentation space."""
    if not isinstance(code, str):
        raise TypeError("human email code must be a string")
    if _HUMAN_CODE_PATTERN.fullmatch(code):
        return code
    if _HUMAN_CODE_DISPLAY_PATTERN.fullmatch(code):
        return code.replace(" ", "")
    raise InvalidHumanEmailCode("human email code is invalid")


def format_human_email_code(code: str) -> str:
    """Render an already-valid code in the sole supported display format."""
    normalized = normalize_human_email_code(code)
    return f"{normalized[:4]} {normalized[4:]}"


def _frame_field(value: bytes) -> bytes:
    return struct.pack(">I", len(value)) + value


def _require_uuid(value: uuid.UUID, *, name: str) -> uuid.UUID:
    if not isinstance(value, uuid.UUID):
        raise TypeError(f"{name} must be a UUID")
    return value


def email_verification_code_hmac_message(
    *,
    challenge_id: uuid.UUID,
    user_id: uuid.UUID,
    user_email_id: uuid.UUID,
    code: str,
) -> bytes:
    """Build the versioned, length-prefixed HMAC message frozen by ADR-008."""
    challenge_id = _require_uuid(challenge_id, name="challenge_id")
    user_id = _require_uuid(user_id, name="user_id")
    user_email_id = _require_uuid(user_email_id, name="user_email_id")
    normalized_code = normalize_human_email_code(code)
    protocol = EMAIL_VERIFICATION_CODE_HMAC_PROTOCOL.encode("ascii")
    purpose = EMAIL_VERIFICATION_CODE_HMAC_PURPOSE.encode("ascii")
    code_bytes = normalized_code.encode("ascii")
    return b"".join(
        (
            _frame_field(protocol),
            _frame_field(challenge_id.bytes),
            _frame_field(purpose),
            _frame_field(user_id.bytes),
            _frame_field(user_email_id.bytes),
            _frame_field(code_bytes),
        )
    )


def email_verification_code_digest(
    *,
    key: bytes,
    challenge_id: uuid.UUID,
    user_id: uuid.UUID,
    user_email_id: uuid.UUID,
    code: str,
) -> bytes:
    """Calculate the full 32-byte HMAC-SHA-256 digest for a normalized code."""
    key = _require_bytes(key, name="HMAC key")
    message = email_verification_code_hmac_message(
        challenge_id=challenge_id,
        user_id=user_id,
        user_email_id=user_email_id,
        code=code,
    )
    return hmac.digest(key, message, "sha256")


def verify_email_verification_code_digest(
    *,
    expected_digest: bytes,
    key: bytes,
    challenge_id: uuid.UUID,
    user_id: uuid.UUID,
    user_email_id: uuid.UUID,
    code: str,
) -> bool:
    """Compare a computed code digest with the stored digest in constant time."""
    expected_digest = _require_bytes(expected_digest, name="expected digest")
    if len(expected_digest) != HMAC_DIGEST_LENGTH:
        return False
    actual_digest = email_verification_code_digest(
        key=key,
        challenge_id=challenge_id,
        user_id=user_id,
        user_email_id=user_email_id,
        code=code,
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def _decode_hmac_key(encoded_key: str) -> bytes:
    if not isinstance(encoded_key, str) or not encoded_key:
        raise InvalidEmailVerificationHmacConfiguration(
            "email verification HMAC key is invalid"
        )
    if "=" in encoded_key or not re.fullmatch(r"[A-Za-z0-9_-]+", encoded_key):
        raise InvalidEmailVerificationHmacConfiguration(
            "email verification HMAC key is invalid"
        )
    padding = "=" * (-len(encoded_key) % 4)
    try:
        key = base64.urlsafe_b64decode(encoded_key + padding)
    except (ValueError, UnicodeEncodeError) as error:
        raise InvalidEmailVerificationHmacConfiguration(
            "email verification HMAC key is invalid"
        ) from error
    canonical = base64.urlsafe_b64encode(key).decode("ascii").rstrip("=")
    if canonical != encoded_key or len(key) < HMAC_KEY_MINIMUM_BYTES:
        raise InvalidEmailVerificationHmacConfiguration(
            "email verification HMAC key is invalid"
        )
    return key


class EmailVerificationHmacKeyring:
    """Validated keyring with exact-version lookup and no implicit fallback."""

    def __init__(
        self,
        *,
        active_key_version: str | None,
        keys: Mapping[str, SecretStr | str] | None,
    ) -> None:
        if not isinstance(active_key_version, str) or not 1 <= len(active_key_version) <= 64:
            raise InvalidEmailVerificationHmacConfiguration(
                "email verification HMAC active key version is invalid"
            )
        if not keys:
            raise InvalidEmailVerificationHmacConfiguration(
                "email verification HMAC keyring is empty"
            )
        decoded_keys: dict[str, bytes] = {}
        for version, configured_key in keys.items():
            if not isinstance(version, str) or not 1 <= len(version) <= 64:
                raise InvalidEmailVerificationHmacConfiguration(
                    "email verification HMAC key version is invalid"
                )
            secret = (
                configured_key.get_secret_value()
                if isinstance(configured_key, SecretStr)
                else configured_key
            )
            decoded_keys[version] = _decode_hmac_key(secret)
        if active_key_version not in decoded_keys:
            raise InvalidEmailVerificationHmacConfiguration(
                "email verification HMAC active key version is not configured"
            )
        self._active_key_version = active_key_version
        self._keys = decoded_keys

    @classmethod
    def from_settings(cls, settings: object) -> "EmailVerificationHmacKeyring":
        """Build a strict keyring only when the email-verification component is used."""
        active_key_version = getattr(settings, "email_verification_hmac_active_key_version", None)
        keys = getattr(settings, "email_verification_hmac_keys", None)
        return cls(active_key_version=active_key_version, keys=keys)

    @property
    def active_key_version(self) -> str:
        return self._active_key_version

    def active_key(self) -> bytes:
        return self._keys[self._active_key_version]

    def key_for_version(self, version: str) -> bytes:
        if not isinstance(version, str):
            raise TypeError("HMAC key version must be a string")
        try:
            return self._keys[version]
        except KeyError as error:
            raise UnknownEmailVerificationHmacKeyVersion(
                "email verification HMAC key version is unknown"
            ) from error

    def __repr__(self) -> str:
        return (
            "EmailVerificationHmacKeyring("
            f"active_key_version={self._active_key_version!r}, key_count={len(self._keys)!r})"
        )
