"""Email validation and canonicalization for authentication identity."""

from dataclasses import dataclass

from email_validator import EmailNotValidError, validate_email


class EmailValidationError(ValueError):
    """Raised when an email address is outside the supported identity contract."""


@dataclass(frozen=True)
class CanonicalEmail:
    """The preserved display value and comparison value of a validated email."""

    display: str
    canonical: str


def validate_and_canonicalize_email(email: str) -> CanonicalEmail:
    """Validate an ASCII-local-part email and derive its comparison identity.

    Only outer whitespace is removed. The display value otherwise remains the
    accepted input; canonicalization lowercases the ASCII local part and uses the
    validator's normalized ASCII domain, without provider-specific rewriting.
    """
    if not isinstance(email, str):
        raise TypeError("email must be a string")

    email_display = email.strip()
    try:
        validated = validate_email(
            email_display,
            allow_smtputf8=False,
            check_deliverability=False,
        )
    except EmailNotValidError as error:
        raise EmailValidationError("email address is invalid") from error

    if not validated.local_part.isascii():
        raise EmailValidationError("email address is invalid")

    return CanonicalEmail(
        display=email_display,
        canonical=f"{validated.local_part.lower()}@{validated.ascii_domain.lower()}",
    )
