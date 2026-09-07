import pytest
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, UnsupportedParametersError, VerificationError

import app.auth.passwords as passwords
from app.auth.passwords import (
    MAXIMUM_PASSWORD_LENGTH,
    MINIMUM_PASSWORD_LENGTH,
    PasswordPolicyError,
    PasswordVerificationError,
    hash_password,
    password_needs_rehash,
    validate_password,
    verify_password,
)


def test_hash_does_not_contain_plaintext_and_uses_argon2id() -> None:
    password = "correct horse battery staple"

    password_hash = hash_password(password)

    assert password not in password_hash
    assert password_hash.startswith("$argon2id$")


def test_same_password_has_unique_hashes_that_both_verify() -> None:
    password = "correct horse battery staple"

    first_hash = hash_password(password)
    second_hash = hash_password(password)

    assert first_hash != second_hash
    assert verify_password(first_hash, password)
    assert verify_password(second_hash, password)


def test_generated_hash_has_expected_parameters() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert "$argon2id$v=19$m=65536,t=3,p=4$" in password_hash


def test_correct_password_verifies() -> None:
    password = "correct horse battery staple"

    assert verify_password(hash_password(password), password)


def test_incorrect_password_does_not_verify() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert not verify_password(password_hash, "incorrect horse battery staple")


def test_unicode_password_verifies() -> None:
    password = "senha muito segura com caf\u00e9 \U0001f680"

    assert verify_password(hash_password(password), password)


def test_unicode_is_not_normalized() -> None:
    composed = "x" * 14 + "\u00e9"
    decomposed = "x" * 14 + "e\u0301"

    assert verify_password(hash_password(composed), composed)
    assert not verify_password(hash_password(composed), decomposed)


def test_password_with_spaces_remains_exact() -> None:
    password = "  a password with leading and trailing spaces  "

    assert verify_password(hash_password(password), password)
    assert not verify_password(hash_password(password), password.strip())


def test_minimum_length_password_is_allowed() -> None:
    password = "a" * MINIMUM_PASSWORD_LENGTH

    validate_password(password)
    assert verify_password(hash_password(password), password)


def test_password_below_minimum_is_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="at least"):
        hash_password("a" * (MINIMUM_PASSWORD_LENGTH - 1))


def test_long_password_is_allowed() -> None:
    password = "a" * 512

    assert verify_password(hash_password(password), password)


def test_password_above_technical_limit_is_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="at most"):
        hash_password("a" * (MAXIMUM_PASSWORD_LENGTH + 1))


def test_verification_rejects_password_above_technical_limit_before_argon2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def verify_should_not_run(password_hash: str, password: str) -> bool:
        nonlocal called
        called = True
        return False

    class PasswordHasherThatMustNotRun:
        def verify(self, password_hash: str, password: str) -> bool:
            return verify_should_not_run(password_hash, password)

    monkeypatch.setattr(passwords, "_PASSWORD_HASHER", PasswordHasherThatMustNotRun())

    with pytest.raises(PasswordPolicyError, match="at most"):
        verify_password("not-a-hash", "a" * (MAXIMUM_PASSWORD_LENGTH + 1))

    assert not called


@pytest.mark.parametrize("password", [None, 123])
def test_password_input_must_be_a_string(password: object) -> None:
    with pytest.raises(TypeError, match="password must be a string"):
        hash_password(password)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="password must be a string"):
        verify_password("not-a-hash", password)  # type: ignore[arg-type]


def test_verification_allows_password_below_creation_minimum() -> None:
    old_password = "short"
    old_hash = PasswordHasher(type=Type.ID, encoding="utf-8").hash(old_password)

    assert verify_password(old_hash, old_password)


def test_invalid_hash_does_not_verify() -> None:
    assert not verify_password("not-a-hash", "correct horse battery staple")


def test_corrupt_encoded_hash_raises_safe_domain_error() -> None:
    with pytest.raises(PasswordVerificationError, match="password hash verification failed"):
        verify_password("$argon2id$invalid", "correct horse battery staple")


def test_generic_verification_error_is_not_converted_to_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_verification(password_hash: str, password: str) -> bool:
        raise VerificationError("internal detail")

    class PasswordHasherWithVerificationFailure:
        def verify(self, password_hash: str, password: str) -> bool:
            return fail_verification(password_hash, password)

    monkeypatch.setattr(
        passwords,
        "_PASSWORD_HASHER",
        PasswordHasherWithVerificationFailure(),
    )

    with pytest.raises(
        PasswordVerificationError,
        match="password hash verification failed",
    ) as error:
        verify_password("valid-looking-hash", "correct horse battery staple")

    assert isinstance(error.value.__cause__, VerificationError)


def test_unsupported_parameters_error_is_not_converted_to_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_for_unsupported_parameters(password_hash: str, password: str) -> bool:
        raise UnsupportedParametersError("platform detail")

    class PasswordHasherWithUnsupportedParameters:
        def verify(self, password_hash: str, password: str) -> bool:
            return fail_for_unsupported_parameters(password_hash, password)

    monkeypatch.setattr(
        passwords,
        "_PASSWORD_HASHER",
        PasswordHasherWithUnsupportedParameters(),
    )

    with pytest.raises(UnsupportedParametersError, match="platform detail"):
        verify_password("valid-looking-hash", "correct horse battery staple")


def test_current_hash_does_not_need_rehash() -> None:
    assert not password_needs_rehash(hash_password("correct horse battery staple"))


def test_weaker_hash_needs_rehash() -> None:
    old_hasher = PasswordHasher(
        time_cost=2,
        memory_cost=32768,
        parallelism=2,
        hash_len=16,
        salt_len=16,
        type=Type.ID,
    )

    assert password_needs_rehash(old_hasher.hash("correct horse battery staple"))


def test_invalid_hash_does_not_silently_skip_rehash() -> None:
    with pytest.raises(InvalidHashError):
        password_needs_rehash("not-a-hash")
