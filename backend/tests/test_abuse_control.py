import base64
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth.abuse_control import (
    HKDF_PURPOSE_ACTION_PIN,
    HKDF_PURPOSE_APPROVAL_CODE,
    HKDF_PURPOSE_RATE_LIMIT,
    HKDF_PURPOSE_RESET_CODE,
    AbuseControlKey,
    AbuseController,
    ClientAddressUnavailable,
    _hkdf_expand,
    client_network,
)
from app.db.models import AuthAbuseBucket

pytestmark = pytest.mark.postgresql


def abuse_key() -> AbuseControlKey:
    encoded = base64.urlsafe_b64encode(b"a" * 32).decode("ascii").rstrip("=")
    return AbuseControlKey(SecretStr(encoded))


def controller(engine: Engine) -> AbuseController:
    return AbuseController(sessionmaker(bind=engine), abuse_key())


def test_identifier_pseudonyms_are_fixed_length_and_do_not_contain_email() -> None:
    key = abuse_key()
    known = key.pseudonymize("auth-abuse:identifier", "known@example.com")
    unknown = key.pseudonymize("auth-abuse:identifier", "unknown@example.com")

    assert len(known) == len(unknown) == 32
    assert known != unknown
    assert "known@example.com" not in repr(key)


def test_client_network_ignores_xff_when_peer_is_not_the_trusted_proxy() -> None:
    peer_network = "198.51.100.0/24"
    assert (
        client_network("198.51.100.25", trusted_proxy_ip=None, forwarded_for=None)
        == peer_network
    )
    assert client_network(
        "198.51.100.25", trusted_proxy_ip=None, forwarded_for="203.0.113.99"
    ) == peer_network
    assert client_network(
        "198.51.100.25",
        trusted_proxy_ip="192.0.2.25",
        forwarded_for="203.0.113.99, 192.0.2.1",
    ) == peer_network


@pytest.mark.parametrize(
    "forwarded_for",
    ["203.0.113.99", "not-an-ip", "", "203.0.113.99, 192.0.2.1"],
)
def test_untrusted_peer_always_uses_socket_peer_even_with_false_xff(
    forwarded_for: str,
) -> None:
    assert (
        client_network(
            "198.51.100.25",
            trusted_proxy_ip="192.0.2.25",
            forwarded_for=forwarded_for,
        )
        == "198.51.100.0/24"
    )


def test_trusted_proxy_uses_exactly_one_valid_forwarded_client_address() -> None:
    assert client_network(
        "198.51.100.25", trusted_proxy_ip="198.51.100.25", forwarded_for="203.0.113.99"
    ) == "203.0.113.0/24"
    assert client_network(
        "198.51.100.25",
        trusted_proxy_ip="198.51.100.25",
        forwarded_for="2001:db8:1234:5678::1",
    ) == "2001:db8:1234:5678::/64"


@pytest.mark.parametrize(
    "forwarded_for",
    [
        None,
        "",
        "   ",
        "not-an-ip",
        "203.0.113.99, 192.0.2.1",
        ("203.0.113.99", "192.0.2.1"),
    ],
)
def test_trusted_proxy_rejects_ambiguous_or_invalid_xff_without_proxy_fallback(
    forwarded_for: str | tuple[str, ...] | None,
) -> None:
    with pytest.raises(ClientAddressUnavailable):
        client_network(
            "198.51.100.25",
            trusted_proxy_ip="198.51.100.25",
            forwarded_for=forwarded_for,
        )


def test_registration_budget_is_atomic_under_real_postgresql_concurrency(
    migrated_postgresql_engine: Engine,
) -> None:
    email = f"limiter-{uuid.uuid4()}@example.com"
    network = f"198.51.{uuid.uuid4().int % 255}.0/24"

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _: controller(migrated_postgresql_engine).admit_registration(
                    canonical_email=email, network=network
                ),
                range(8),
            )
        )

    assert results.count(True) == 5
    assert results.count(False) == 3
    with Session(migrated_postgresql_engine) as session:
        buckets = session.scalars(
            select(AuthAbuseBucket).where(AuthAbuseBucket.operation == "registration")
        ).all()
        identifier = next(bucket for bucket in buckets if bucket.dimension == "identifier")
        assert identifier.count == 5
        assert email.encode() not in identifier.bucket_key


def test_expired_bucket_resets_and_cleanup_removes_expired_rows(
    migrated_postgresql_engine: Engine,
) -> None:
    email = f"expiry-{uuid.uuid4()}@example.com"
    network = "203.0.113.0/24"
    abuse = controller(migrated_postgresql_engine)

    assert abuse.admit_resend(canonical_email=email, network=network)
    with Session(migrated_postgresql_engine) as session, session.begin():
        bucket = session.scalar(
            select(AuthAbuseBucket).where(
                AuthAbuseBucket.operation == "email_verification_resend",
                AuthAbuseBucket.dimension == "identifier",
            )
        )
        assert bucket is not None
        bucket.window_started_at = datetime.now(UTC) - timedelta(seconds=2)
        bucket.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert abuse.admit_resend(canonical_email=email, network=network)
    with Session(migrated_postgresql_engine) as session:
        bucket = session.scalar(
            select(AuthAbuseBucket).where(
                AuthAbuseBucket.operation == "email_verification_resend",
                AuthAbuseBucket.dimension == "identifier",
            )
        )
        assert bucket is not None and bucket.count == 1
    with Session(migrated_postgresql_engine) as session, session.begin():
        for bucket in session.scalars(select(AuthAbuseBucket)).all():
            bucket.window_started_at = datetime.now(UTC) - timedelta(seconds=2)
            bucket.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert abuse.cleanup_expired() > 0
    with Session(migrated_postgresql_engine) as session:
        assert session.scalar(select(AuthAbuseBucket)) is None


# ---------- HKDF key derivation (ADR-038) ----------


def test_hkdf_expand_produces_32_bytes_deterministically() -> None:
    prk = b"a" * 32
    out1 = _hkdf_expand(prk, b"aval/rate-limit/v1", 32)
    out2 = _hkdf_expand(prk, b"aval/rate-limit/v1", 32)
    assert len(out1) == 32
    assert out1 == out2  # deterministic


def test_hkdf_different_purposes_yield_different_subkeys() -> None:
    key = abuse_key()
    purposes = [
        HKDF_PURPOSE_RATE_LIMIT,
        HKDF_PURPOSE_RESET_CODE,
        HKDF_PURPOSE_APPROVAL_CODE,
        HKDF_PURPOSE_ACTION_PIN,
    ]
    subkeys = [key.derive(p) for p in purposes]
    # All are 32 bytes.
    assert all(len(sk) == 32 for sk in subkeys)
    # All are distinct.
    assert len(set(subkeys)) == len(purposes)


def test_hkdf_derived_mac_differs_from_legacy_raw_key_mac() -> None:
    """The whole point: a MAC computed with a derived subkey must NOT match
    one computed with the raw master key (legacy scheme)."""
    key = abuse_key()
    # Legacy: HMAC directly with the master key (simulated).
    import hashlib
    import hmac as _hmac

    legacy = _hmac.digest(key._key, b"action-pin\x00some-value", hashlib.sha256)
    derived = key.pseudonymize("action-pin", "some-value", purpose=HKDF_PURPOSE_ACTION_PIN)
    assert legacy != derived


def test_derive_caches_subkey() -> None:
    key = abuse_key()
    first = key.derive(HKDF_PURPOSE_RATE_LIMIT)
    second = key.derive(HKDF_PURPOSE_RATE_LIMIT)
    assert first is second  # same object, not just equal


def test_derive_rejects_empty_purpose() -> None:
    key = abuse_key()
    with pytest.raises(ValueError, match="purpose must not be empty"):
        key.derive(b"")
