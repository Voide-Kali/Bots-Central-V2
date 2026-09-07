"""Password hashing and validation primitives for the authentication domain."""

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MINIMUM_PASSWORD_LENGTH = 15
"""Minimum password length, measured in Unicode characters."""

MAXIMUM_PASSWORD_LENGTH = 1024
"""Technical password input limit, measured in Unicode characters."""

_PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    encoding="utf-8",
    type=Type.ID,
)


class PasswordPolicyError(ValueError):
    """Raised when a password does not meet the input-size policy."""


class PasswordVerificationError(RuntimeError):
    """Raised when Argon2 cannot complete password hash verification safely."""


def _validate_password_input(password: str) -> None:
    """Validate the type and technical input limit used for all password operations."""
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    if len(password) > MAXIMUM_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"password must contain at most {MAXIMUM_PASSWORD_LENGTH} characters"
        )


def validate_password(password: str) -> None:
    """Validate the password policy for password creation or change."""
    _validate_password_input(password)
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"password must contain at least {MINIMUM_PASSWORD_LENGTH} characters"
        )


def hash_password(password: str) -> str:
    """Validate and hash a password using the explicit Argon2id profile."""
    validate_password(password)
    return _PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Return whether a password matches an Argon2 hash.

    Mismatches and malformed hashes return ``False``. Generic Argon2 verification
    failures are raised as :class:`PasswordVerificationError`; platform and other
    unexpected failures intentionally propagate.
    """
    _validate_password_input(password)
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except VerificationError as error:
        raise PasswordVerificationError("password hash verification failed") from error


def password_needs_rehash(password_hash: str) -> bool:
    """Return whether a valid password hash differs from the current profile.

    Invalid or corrupt hashes raise the library error instead of being treated as
    current hashes.
    """
    return _PASSWORD_HASHER.check_needs_rehash(password_hash)
