"""Small PostgreSQL-backed admission control for anonymous auth operations."""

import base64
import hashlib
import hmac
import ipaddress
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from pydantic import SecretStr
from sqlalchemy import delete, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import AuthAbuseBucket

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_KEY_MINIMUM_BYTES = 32


class InvalidAbuseControlConfiguration(ValueError):
    """Raised when the separately configured limiter HMAC key is unsafe."""


class AbuseControlUnavailable(RuntimeError):
    """Fail-closed result when shared admission state cannot be consulted."""


class ClientAddressUnavailable(ValueError):
    """Raised when a public request has no usable peer address."""


class _AdmissionDenied(Exception):
    pass


@dataclass(frozen=True)
class AbuseLimit:
    dimension: str
    maximum: int
    window_seconds: int


@dataclass(frozen=True)
class AbusePolicy:
    operation: str
    limits: tuple[AbuseLimit, ...]


REGISTRATION_POLICY = AbusePolicy(
    operation="registration",
    limits=(
        AbuseLimit("identifier", 5, 3600),
        AbuseLimit("network", 30, 3600),
        AbuseLimit("global", 300, 60),
    ),
)
LOGIN_POLICY = AbusePolicy(
    operation="login",
    limits=(
        AbuseLimit("identifier", 10, 3600),
        AbuseLimit("network", 60, 3600),
        AbuseLimit("global", 600, 60),
    ),
)
RESEND_POLICY = AbusePolicy(
    operation="email_verification_resend",
    limits=(
        AbuseLimit("identifier", 5, 3600),
        AbuseLimit("network", 20, 3600),
        AbuseLimit("global", 300, 3600),
    ),
)
CODE_CONSUME_POLICY = AbusePolicy(
    operation="email_verification_consume_code",
    limits=(
        AbuseLimit("challenge", 10, 900),
        AbuseLimit("network", 30, 900),
        AbuseLimit("global", 1000, 900),
    ),
)
LINK_CONSUME_POLICY = AbusePolicy(
    operation="email_verification_consume_link",
    limits=(
        AbuseLimit("network", 60, 900),
        AbuseLimit("global", 1500, 900),
    ),
)
HEARTBEAT_POLICY = AbusePolicy(
    operation="device_heartbeat",
    limits=(
        AbuseLimit("device", 10, 60),
        AbuseLimit("global", 5000, 60),
    ),
)
HEARTBEAT_PREAUTH_POLICY = AbusePolicy(
    operation="device_heartbeat_preauth",
    limits=(
        AbuseLimit("network", 120, 60),
        AbuseLimit("global", 10000, 60),
    ),
)

SessionFactory = Callable[[], Session]

_ADMIT_BUCKET = text(
    """
    INSERT INTO auth_abuse_buckets (
        operation, dimension, bucket_key, count, window_started_at, expires_at
    )
    VALUES (
        :operation,
        :dimension,
        :bucket_key,
        1,
        clock_timestamp(),
        clock_timestamp() + make_interval(secs => CAST(:window_seconds AS integer))
    )
    ON CONFLICT (operation, dimension, bucket_key) DO UPDATE
    SET
        count = CASE
            WHEN auth_abuse_buckets.expires_at <= clock_timestamp() THEN 1
            ELSE auth_abuse_buckets.count + 1
        END,
        window_started_at = CASE
            WHEN auth_abuse_buckets.expires_at <= clock_timestamp() THEN clock_timestamp()
            ELSE auth_abuse_buckets.window_started_at
        END,
        expires_at = CASE
            WHEN auth_abuse_buckets.expires_at <= clock_timestamp()
            THEN clock_timestamp() + make_interval(secs => CAST(:window_seconds AS integer))
            ELSE auth_abuse_buckets.expires_at
        END
    WHERE
        auth_abuse_buckets.expires_at <= clock_timestamp()
        OR auth_abuse_buckets.count < :maximum
    RETURNING count
    """
)


def _decode_key(encoded: str) -> bytes:
    if not encoded or "=" in encoded or not _KEY_PATTERN.fullmatch(encoded):
        raise InvalidAbuseControlConfiguration("abuse-control HMAC key is invalid")
    try:
        key = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, UnicodeEncodeError) as error:
        raise InvalidAbuseControlConfiguration("abuse-control HMAC key is invalid") from error
    if (
        len(key) < _KEY_MINIMUM_BYTES
        or base64.urlsafe_b64encode(key).decode("ascii").rstrip("=") != encoded
    ):
        raise InvalidAbuseControlConfiguration("abuse-control HMAC key is invalid")
    return key


class AbuseControlKey:
    """Separate keyed pseudonymization primitive; never reuse email-code HMAC keys."""

    def __init__(self, encoded_key: SecretStr | str | None) -> None:
        secret = (
            encoded_key.get_secret_value()
            if isinstance(encoded_key, SecretStr)
            else encoded_key
        )
        if not isinstance(secret, str):
            raise InvalidAbuseControlConfiguration("abuse-control HMAC key is not configured")
        self._key = _decode_key(secret)

    @classmethod
    def from_settings(cls, settings: object) -> "AbuseControlKey":
        return cls(getattr(settings, "abuse_control_hmac_key", None))

    def pseudonymize(self, namespace: str, value: str) -> bytes:
        if not namespace or not isinstance(value, str):
            raise TypeError("abuse-control namespace and value must be strings")
        return hmac.digest(self._key, f"{namespace}\x00{value}".encode(), hashlib.sha256)

    def __repr__(self) -> str:
        return "AbuseControlKey(configured=True)"


def client_network(
    peer_ip: str,
    *,
    trusted_proxy_ip: str | None,
    forwarded_for: str | tuple[str, ...] | None,
) -> str:
    """Return the /24 or /64 network from a peer or one unambiguous trusted-proxy header."""
    try:
        peer = ipaddress.ip_address(peer_ip)
    except ValueError as error:
        raise ClientAddressUnavailable("public request has no usable peer address") from error
    selected = peer
    if trusted_proxy_ip is not None and peer.compressed == trusted_proxy_ip:
        values = (forwarded_for,) if isinstance(forwarded_for, str) else forwarded_for or ()
        if len(values) != 1 or not values[0].strip() or "," in values[0]:
            raise ClientAddressUnavailable("trusted proxy did not supply one usable client address")
        try:
            selected = ipaddress.ip_address(values[0].strip())
        except ValueError as error:
            raise ClientAddressUnavailable(
                "trusted proxy did not supply one usable client address"
            ) from error
    prefix = 24 if selected.version == 4 else 64
    return str(ipaddress.ip_network(f"{selected}/{prefix}", strict=False))


class AbuseController:
    """Atomically admit all dimensions or consume no public-auth budget at all."""

    def __init__(self, session_factory: SessionFactory, key: AbuseControlKey) -> None:
        self._session_factory = session_factory
        self._key = key

    def _bucket_key(self, dimension: str, value: str) -> bytes:
        return self._key.pseudonymize(f"auth-abuse:{dimension}", value)

    def _admit(self, policy: AbusePolicy, values: dict[str, str]) -> bool:
        try:
            with self._session_factory() as session:
                try:
                    with session.begin():
                        for limit in policy.limits:
                            value = values[limit.dimension]
                            admitted = session.execute(
                                _ADMIT_BUCKET,
                                {
                                    "operation": policy.operation,
                                    "dimension": limit.dimension,
                                    "bucket_key": self._bucket_key(limit.dimension, value),
                                    "maximum": limit.maximum,
                                    "window_seconds": limit.window_seconds,
                                },
                            ).scalar_one_or_none()
                            if admitted is None:
                                raise _AdmissionDenied
                except _AdmissionDenied:
                    return False
        except SQLAlchemyError as error:
            raise AbuseControlUnavailable(
                "shared abuse-control authority is unavailable"
            ) from error
        return True

    def admit_registration(self, *, canonical_email: str, network: str) -> bool:
        return self._admit(
            REGISTRATION_POLICY,
            {"identifier": canonical_email, "network": network, "global": "all"},
        )

    def admit_login(self, *, canonical_email: str, network: str) -> bool:
        return self._admit(
            LOGIN_POLICY,
            {"identifier": canonical_email, "network": network, "global": "all"},
        )

    def admit_resend(self, *, canonical_email: str, network: str) -> bool:
        return self._admit(
            RESEND_POLICY,
            {"identifier": canonical_email, "network": network, "global": "all"},
        )

    def admit_code_consume(self, *, challenge_id: uuid.UUID, network: str) -> bool:
        return self._admit(
            CODE_CONSUME_POLICY,
            {"challenge": str(challenge_id), "network": network, "global": "all"},
        )

    def admit_link_consume(self, *, network: str) -> bool:
        return self._admit(LINK_CONSUME_POLICY, {"network": network, "global": "all"})

    def admit_heartbeat(self, *, device_id: uuid.UUID) -> bool:
        return self._admit(
            HEARTBEAT_POLICY,
            {"device": str(device_id), "global": "all"},
        )

    def admit_heartbeat_preauth(self, *, network: str) -> bool:
        return self._admit(
            HEARTBEAT_PREAUTH_POLICY,
            {"network": network, "global": "all"},
        )

    def cleanup_expired(self) -> int:
        """Delete expired rows; callers may run this as bounded operational maintenance."""
        try:
            with self._session_factory() as session, session.begin():
                result = cast(
                    CursorResult[object],
                    session.execute(
                        delete(AuthAbuseBucket).where(
                            AuthAbuseBucket.expires_at <= text("clock_timestamp()")
                        )
                    ),
                )
        except SQLAlchemyError as error:
            raise AbuseControlUnavailable(
                "shared abuse-control authority is unavailable"
            ) from error
        return result.rowcount or 0
