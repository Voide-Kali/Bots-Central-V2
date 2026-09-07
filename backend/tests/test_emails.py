import pytest

from app.auth.emails import EmailValidationError, validate_and_canonicalize_email


def test_valid_email_preserves_display_and_canonicalizes_for_comparison() -> None:
    result = validate_and_canonicalize_email("User.Name+tag@Example.COM")

    assert result.display == "User.Name+tag@Example.COM"
    assert result.canonical == "user.name+tag@example.com"


def test_outer_whitespace_is_removed_from_display() -> None:
    result = validate_and_canonicalize_email("  User@Example.COM  ")

    assert result.display == "User@Example.COM"
    assert result.canonical == "user@example.com"


def test_domain_and_ascii_local_part_are_case_insensitive_for_comparison() -> None:
    first = validate_and_canonicalize_email("User@Example.COM")
    second = validate_and_canonicalize_email("user@example.com")

    assert first.canonical == second.canonical


def test_provider_specific_parts_are_not_rewritten() -> None:
    result = validate_and_canonicalize_email("User.Name+tag@gmail.com")

    assert result.canonical == "user.name+tag@gmail.com"


@pytest.mark.parametrize("email", ["not-an-email", "user@localhost", "us\u00e9r@example.com"])
def test_invalid_or_out_of_scope_email_is_rejected(email: str) -> None:
    with pytest.raises(EmailValidationError, match="email address is invalid"):
        validate_and_canonicalize_email(email)


@pytest.mark.parametrize("email", [None, 123])
def test_email_must_be_a_string(email: object) -> None:
    with pytest.raises(TypeError, match="email must be a string"):
        validate_and_canonicalize_email(email)  # type: ignore[arg-type]
