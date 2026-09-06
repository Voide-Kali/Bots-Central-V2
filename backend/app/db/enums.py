from enum import StrEnum


def persisted_enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class AccountStatus(StrEnum):
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    LOCKED = "locked"
    DISABLED = "disabled"


class AuthenticationLevel(StrEnum):
    PASSWORD_AUTHENTICATED = "password_authenticated"


class SessionRevocationReason(StrEnum):
    LOGOUT = "logout"
    USER_REVOKED = "user_revoked"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET = "password_reset"
    EMAIL_CHANGED = "email_changed"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_DISABLED = "account_disabled"
    REFRESH_REUSE_DETECTED = "refresh_reuse_detected"
    SECURITY_CONTAINMENT = "security_containment"
