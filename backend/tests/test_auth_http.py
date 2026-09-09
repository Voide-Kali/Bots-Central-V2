import base64
import uuid
from collections.abc import Generator, Mapping, MutableMapping
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import anyio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from httpx import Response as HttpxResponse
from pydantic import SecretStr
from sqlalchemy import delete, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.routes import auth as auth_route
from app.auth import email_verification_application as application
from app.auth import registration
from app.auth.abuse_control import AbuseControlKey, AbuseController, AbuseControlUnavailable
from app.auth.email_verification_consume import (
    AccountNotEligible,
    AttemptsExhausted,
    EmailVerificationConsumeOutcome,
    Expired,
    Invalidated,
    InvalidChallenge,
    KeyVersionUnavailable,
    MalformedCode,
    WrongCode,
)
from app.auth.email_verification_delivery import DeliveryIntent
from app.auth.email_verification_materials import EmailVerificationHmacKeyring
from app.core.config import Settings
from app.db.enums import AccountStatus
from app.db.enums import EmailVerificationInvalidationReason as Reason
from app.db.enums import EmailVerificationMaterialType as Material
from app.db.models import EmailVerificationChallenge as Challenge
from app.db.models import PasswordCredential, User, UserEmail
from app.main import create_app

pytestmark = pytest.mark.postgresql


def encoded_key(byte: bytes = b"a") -> str:
    return base64.urlsafe_b64encode(byte * 32).decode("ascii").rstrip("=")


def keyring() -> EmailVerificationHmacKeyring:
    return EmailVerificationHmacKeyring(
        active_key_version="current",
        keys={"current": SecretStr(encoded_key())},
    )


class RecordingAdapter:
    def __init__(self, body_events: list[dict[str, object]] | None = None) -> None:
        self.intents: list[DeliveryIntent] = []
        self.body_events = body_events

    def deliver(self, intent: DeliveryIntent) -> None:
        if self.body_events is not None:
            assert any(event["type"] == "http.response.body" for event in self.body_events)
        self.intents.append(intent)


def auth_settings() -> Settings:
    return Settings(
        public_origin="http://localhost:8000",
        abuse_control_hmac_key=SecretStr(encoded_key(b"b")),
    )


def auth_app(
    engine: Engine, adapter: RecordingAdapter, *, material: Material = Material.LINK
) -> FastAPI:
    settings = auth_settings()
    app = create_app()
    app.state.auth_runtime = auth_route.AuthHttpRuntime(
        session_factory=sessionmaker(bind=engine),
        abuse_controller=AbuseController(
            sessionmaker(bind=engine), AbuseControlKey.from_settings(settings)
        ),
        keyring=keyring(),
        delivery_adapter=adapter,
        settings=settings.model_copy(update={"email_verification_material_type": material.value}),
        password_limiter=anyio.CapacityLimiter(1),
    )
    return app


@contextmanager
def cleanup_email(engine: Engine, email: str) -> Generator[None, None, None]:
    try:
        yield
    finally:
        with Session(engine) as session, session.begin():
            rows = session.execute(
                select(UserEmail.id, UserEmail.user_id).where(UserEmail.email_canonical == email)
            ).all()
            email_ids = [row[0] for row in rows]
            user_ids = [row[1] for row in rows]
            if email_ids:
                session.execute(delete(Challenge).where(Challenge.user_email_id.in_(email_ids)))
                session.execute(
                    delete(PasswordCredential).where(PasswordCredential.user_id.in_(user_ids))
                )
                session.execute(delete(UserEmail).where(UserEmail.id.in_(email_ids)))
                session.execute(delete(User).where(User.id.in_(user_ids)))


async def post(client: AsyncClient, path: str, payload: Mapping[str, object]) -> HttpxResponse:
    return await client.post(path, json=payload)


@pytest.mark.anyio
async def test_registration_duplicate_is_generic_and_only_new_registration_dispatches(
    migrated_postgresql_engine: Engine,
) -> None:
    email = f"http-register-{uuid.uuid4()}@example.com"
    adapter = RecordingAdapter()
    app = auth_app(migrated_postgresql_engine, adapter)
    payload = {"email": email, "password": "a sufficiently long registration password"}

    with cleanup_email(migrated_postgresql_engine, email):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await post(client, "/api/v1/auth/register", payload)
            duplicate = await post(client, "/api/v1/auth/register", payload)

        assert (created.status_code, created.content, created.headers["cache-control"]) == (
            duplicate.status_code,
            duplicate.content,
            duplicate.headers["cache-control"],
        ) == (
            202,
            b'{"message":"If eligible, verification instructions will be sent."}',
            "no-store",
        )
        assert len(adapter.intents) == 1
        with Session(migrated_postgresql_engine) as session:
            challenge_count = session.scalar(
                select(text("count(*)")).select_from(Challenge).join(UserEmail)
                .where(UserEmail.email_canonical == email)
            )
            assert challenge_count == 1
        assert email not in created.text
        assert payload["password"] not in created.text


@pytest.mark.anyio
async def test_registration_limiter_rejects_before_argon2(
    migrated_postgresql_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DeniedController:
        def admit_registration(self, *, canonical_email: str, network: str) -> bool:
            return False

    adapter = RecordingAdapter()
    app = auth_app(migrated_postgresql_engine, adapter)
    app.state.auth_runtime.abuse_controller = DeniedController()
    hashed = False

    def forbidden_hash(password: str) -> str:
        nonlocal hashed
        hashed = True
        raise AssertionError("Argon2 must not run")

    monkeypatch.setattr(registration, "hash_password", forbidden_hash)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await post(
            client,
            "/api/v1/auth/register",
            {"email": f"limited-{uuid.uuid4()}@example.com", "password": "a" * 15},
        )

    assert response.status_code == 429
    assert not hashed


@pytest.mark.anyio
async def test_registration_fails_closed_when_shared_limiter_is_unavailable(
    migrated_postgresql_engine: Engine,
) -> None:
    class UnavailableController:
        def admit_registration(self, *, canonical_email: str, network: str) -> bool:
            raise AbuseControlUnavailable("test limiter outage")

    app = auth_app(migrated_postgresql_engine, RecordingAdapter())
    app.state.auth_runtime.abuse_controller = UnavailableController()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await post(
            client,
            "/api/v1/auth/register",
            {"email": f"unavailable-{uuid.uuid4()}@example.com", "password": "a" * 15},
        )

    assert response.status_code == 503
    assert "test limiter outage" not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers,marker",
    [
        ([], None),
        ([("x-forwarded-for", "not-an-ip")], "not-an-ip"),
        ([("x-forwarded-for", "")], None),
        ([("x-forwarded-for", "203.0.113.99, 192.0.2.1")], "203.0.113.99"),
        (
            [
                ("x-forwarded-for", "203.0.113.99"),
                ("x-forwarded-for", "192.0.2.1"),
            ],
            "203.0.113.99",
        ),
    ],
)
async def test_trusted_proxy_invalid_xff_fails_closed_before_limiter_admission(
    migrated_postgresql_engine: Engine,
    headers: list[tuple[str, str]],
    marker: str | None,
) -> None:
    class MustNotAdmit:
        called = False

        def admit_resend(self, *, canonical_email: str, network: str) -> bool:
            self.called = True
            raise AssertionError("invalid proxy metadata must not reach limiter admission")

    proxy_ip = "198.51.100.25"
    app = auth_app(migrated_postgresql_engine, RecordingAdapter())
    app.state.auth_runtime.settings = app.state.auth_runtime.settings.model_copy(
        update={"trusted_proxy_ip": proxy_ip}
    )
    controller = MustNotAdmit()
    app.state.auth_runtime.abuse_controller = controller
    transport = ASGITransport(app=app, client=(proxy_ip, 50000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/email-verification/resend",
            json={"email": "proxy-request@example.com"},
            headers=headers,
        )

    assert (response.status_code, response.content) == (
        503,
        b'{"message":"Request temporarily unavailable."}',
    )
    assert not controller.called
    assert proxy_ip not in response.text
    if marker is not None:
        assert marker not in response.text


@pytest.mark.anyio
async def test_resend_outcomes_are_identical_and_only_staged_result_dispatches(
    migrated_postgresql_engine: Engine,
) -> None:
    adapter = RecordingAdapter()
    app = auth_app(migrated_postgresql_engine, adapter)
    staged_email = f"http-staged-{uuid.uuid4()}@example.com"
    cooldown_email = f"http-cooldown-{uuid.uuid4()}@example.com"
    verified_email = f"http-verified-{uuid.uuid4()}@example.com"
    ineligible_email = f"http-ineligible-{uuid.uuid4()}@example.com"
    unknown_email = f"http-unknown-{uuid.uuid4()}@example.com"
    emails = (staged_email, cooldown_email, verified_email, ineligible_email)

    with (
        cleanup_email(migrated_postgresql_engine, staged_email),
        cleanup_email(migrated_postgresql_engine, cooldown_email),
        cleanup_email(migrated_postgresql_engine, verified_email),
        cleanup_email(migrated_postgresql_engine, ineligible_email),
    ):
        with Session(migrated_postgresql_engine) as session, session.begin():
            for email, status in (
                (staged_email, AccountStatus.PENDING_VERIFICATION),
                (ineligible_email, AccountStatus.LOCKED),
            ):
                user = User(status=status)
                session.add(user)
                session.flush()
                session.add(
                    UserEmail(
                        user_id=user.id,
                        email_canonical=email,
                        email_display=email,
                        is_primary=True,
                    )
                )
        for email in (cooldown_email, verified_email):
            application.register_and_stage_email_verification(
                sessionmaker(bind=migrated_postgresql_engine),
                email=email,
                password="a sufficiently long registration password",
                material_type=Material.LINK,
            )
        with Session(migrated_postgresql_engine) as session, session.begin():
            row = session.scalar(
                select(UserEmail).where(UserEmail.email_canonical == verified_email)
            )
            assert row is not None
            timestamp = session.scalar(text("SELECT clock_timestamp()"))
            assert isinstance(timestamp, datetime)
            row.verified_at = timestamp
        adapter.intents.clear()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            responses = [
                await post(client, "/api/v1/auth/email-verification/resend", {"email": email})
                for email in (*emails, unknown_email)
            ]

        assert {(response.status_code, response.content) for response in responses} == {
            (202, b'{"message":"If eligible, verification instructions will be sent."}')
        }
        assert all("retry-after" not in response.headers for response in responses)
        assert len(adapter.intents) == 1


@pytest.mark.anyio
async def test_consume_routes_distinguish_verified_success_and_commit_normal_mutations(
    migrated_postgresql_engine: Engine,
) -> None:
    adapter = RecordingAdapter()
    app = auth_app(migrated_postgresql_engine, adapter, material=Material.CODE)
    code_failure_email = f"http-code-failure-{uuid.uuid4()}@example.com"
    code_success_email = f"http-code-success-{uuid.uuid4()}@example.com"
    link_email = f"http-link-{uuid.uuid4()}@example.com"
    verified_email = f"http-verified-consume-{uuid.uuid4()}@example.com"
    ineligible_email = f"http-ineligible-consume-{uuid.uuid4()}@example.com"

    with (
        cleanup_email(migrated_postgresql_engine, code_failure_email),
        cleanup_email(migrated_postgresql_engine, code_success_email),
        cleanup_email(migrated_postgresql_engine, link_email),
        cleanup_email(migrated_postgresql_engine, verified_email),
        cleanup_email(migrated_postgresql_engine, ineligible_email),
    ):
        code_failure = application.register_and_stage_email_verification(
            sessionmaker(bind=migrated_postgresql_engine),
            email=code_failure_email,
            password="a sufficiently long registration password",
            material_type=Material.CODE,
            keyring=keyring(),
        ).delivery_intent
        code_success = application.register_and_stage_email_verification(
            sessionmaker(bind=migrated_postgresql_engine),
            email=code_success_email,
            password="a sufficiently long registration password",
            material_type=Material.CODE,
            keyring=keyring(),
        ).delivery_intent
        link_intent = application.register_and_stage_email_verification(
            sessionmaker(bind=migrated_postgresql_engine),
            email=link_email,
            password="a sufficiently long registration password",
            material_type=Material.LINK,
        ).delivery_intent
        verified_intent = application.register_and_stage_email_verification(
            sessionmaker(bind=migrated_postgresql_engine),
            email=verified_email,
            password="a sufficiently long registration password",
            material_type=Material.LINK,
        ).delivery_intent
        ineligible_intent = application.register_and_stage_email_verification(
            sessionmaker(bind=migrated_postgresql_engine),
            email=ineligible_email,
            password="a sufficiently long registration password",
            material_type=Material.LINK,
        ).delivery_intent
        assert (
            code_failure is not None
            and code_success is not None
            and link_intent is not None
            and verified_intent is not None
            and ineligible_intent is not None
        )
        with Session(migrated_postgresql_engine) as session, session.begin():
            verified_row = session.scalar(
                select(UserEmail).where(UserEmail.email_canonical == verified_email)
            )
            locked_user = session.scalar(
                select(User).join(UserEmail).where(UserEmail.email_canonical == ineligible_email)
            )
            assert verified_row is not None and locked_user is not None
            timestamp = session.scalar(text("SELECT clock_timestamp()"))
            assert isinstance(timestamp, datetime)
            verified_row.verified_at = timestamp
            locked_user.status = AccountStatus.LOCKED
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            malformed = await post(
                client,
                "/api/v1/auth/email-verification/consume-code",
                {"challenge_id": str(code_failure.challenge_id), "code": "abc"},
            )
            wrong = await post(
                client,
                "/api/v1/auth/email-verification/consume-code",
                {"challenge_id": str(code_failure.challenge_id), "code": "99999999"},
            )
            exhausted = wrong
            for _ in range(4):
                exhausted = await post(
                    client,
                    "/api/v1/auth/email-verification/consume-code",
                    {"challenge_id": str(code_failure.challenge_id), "code": "99999999"},
                )
            invalidated = await post(
                client,
                "/api/v1/auth/email-verification/consume-code",
                {"challenge_id": str(code_failure.challenge_id), "code": "99999999"},
            )
            invalid_challenge = await post(
                client,
                "/api/v1/auth/email-verification/consume-code",
                {"challenge_id": str(uuid.uuid4()), "code": "99999999"},
            )
            code_consumed = await post(
                client,
                "/api/v1/auth/email-verification/consume-code",
                {
                    "challenge_id": str(code_success.challenge_id),
                    "code": code_success.material.get_secret_value(),
                },
            )
            link_consumed = await post(
                client,
                "/api/v1/auth/email-verification/consume-link",
                {"token": link_intent.material.get_secret_value()},
            )
            already_consumed = await post(
                client,
                "/api/v1/auth/email-verification/consume-link",
                {"token": link_intent.material.get_secret_value()},
            )
            already_verified = await post(
                client,
                "/api/v1/auth/email-verification/consume-link",
                {"token": verified_intent.material.get_secret_value()},
            )
            ineligible = await post(
                client,
                "/api/v1/auth/email-verification/consume-link",
                {"token": ineligible_intent.material.get_secret_value()},
            )

        assert {
            (response.status_code, response.content)
            for response in (
                malformed,
                wrong,
                exhausted,
                invalidated,
                invalid_challenge,
                ineligible,
            )
        } == {(400, b'{"verified":false}')}
        assert {
            (response.status_code, response.content)
            for response in (code_consumed, link_consumed, already_consumed, already_verified)
        } == {(200, b'{"verified":true}')}
        with Session(migrated_postgresql_engine) as session:
            code = session.get(Challenge, code_failure.challenge_id)
            code_success_challenge = session.get(Challenge, code_success.challenge_id)
            link = session.get(Challenge, link_intent.challenge_id)
            verified_challenge = session.get(Challenge, verified_intent.challenge_id)
            ineligible_challenge = session.get(Challenge, ineligible_intent.challenge_id)
            code_success_user = session.scalar(
                select(User).join(UserEmail).where(UserEmail.email_canonical == code_success_email)
            )
            link_user = session.scalar(
                select(User).join(UserEmail).where(UserEmail.email_canonical == link_email)
            )
            assert (
                code is not None
                and code.attempt_count == 5
                and code.invalidation_reason is Reason.ATTEMPTS_EXHAUSTED
            )
            assert (
                code_success_challenge is not None
                and code_success_challenge.consumed_at is not None
            )
            assert (
                code_success_user is not None
                and code_success_user.status is AccountStatus.ACTIVE
            )
            assert link is not None and link.consumed_at is not None
            assert link_user is not None and link_user.status is AccountStatus.ACTIVE
            assert (
                verified_challenge is not None
                and verified_challenge.invalidated_at is not None
                and verified_challenge.invalidation_reason is Reason.EMAIL_ALREADY_VERIFIED
            )
            assert (
                ineligible_challenge is not None
                and ineligible_challenge.invalidated_at is not None
                and ineligible_challenge.invalidation_reason is Reason.ACCOUNT_STATE_CHANGED
            )
        for response in (
            malformed,
            wrong,
            exhausted,
            invalidated,
            invalid_challenge,
            ineligible,
            code_consumed,
            link_consumed,
            already_consumed,
            already_verified,
        ):
            assert "attempt" not in response.text
            assert "challenge" not in response.text
        assert code_failure.material.get_secret_value() not in wrong.text
        assert code_success.material.get_secret_value() not in code_consumed.text
        assert link_intent.material.get_secret_value() not in link_consumed.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "outcome",
    [
        WrongCode(attempt_count=1, attempts_remaining=4),
        AttemptsExhausted(),
        MalformedCode(),
        InvalidChallenge(),
        Expired(),
        Invalidated(invalidation_reason=Reason.SUPERSEDED),
        AccountNotEligible(user_email_id=uuid.uuid4(), account_status=AccountStatus.LOCKED),
        KeyVersionUnavailable(),
    ],
)
async def test_all_normal_consume_failures_share_one_public_response(
    migrated_postgresql_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    outcome: EmailVerificationConsumeOutcome,
) -> None:
    app = auth_app(migrated_postgresql_engine, RecordingAdapter())

    def return_outcome(*_: object, **__: object) -> application.ConsumeApplicationResult:
        return application.ConsumeApplicationResult(outcome=outcome)

    monkeypatch.setattr(
        application,
        "consume_email_verification_link_application",
        return_outcome,
    )
    token = base64.urlsafe_b64encode(b"x" * 32).decode("ascii").rstrip("=")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await post(
            client,
            "/api/v1/auth/email-verification/consume-link",
            {"token": token},
        )

    assert (response.status_code, response.content) == (400, b'{"verified":false}')
    assert outcome.__class__.__name__ not in response.text
    assert token not in response.text


@pytest.mark.anyio
async def test_missing_global_keyring_is_sanitized_server_failure(
    migrated_postgresql_engine: Engine,
) -> None:
    app = auth_app(migrated_postgresql_engine, RecordingAdapter(), material=Material.CODE)
    app.state.auth_runtime.keyring = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await post(
            client,
            "/api/v1/auth/email-verification/consume-code",
            {"challenge_id": str(uuid.uuid4()), "code": "99999999"},
        )

    assert (response.status_code, response.content) == (
        503,
        b'{"message":"Request temporarily unavailable."}',
    )
    assert "keyring" not in response.text


@pytest.mark.anyio
async def test_link_page_is_inert_and_has_no_token_or_third_party_resources(
    migrated_postgresql_engine: Engine,
) -> None:
    adapter = RecordingAdapter()
    app = auth_app(migrated_postgresql_engine, adapter)
    with Session(migrated_postgresql_engine) as session:
        before = session.scalar(select(text("count(*)")).select_from(Challenge))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/email-verification#token=not-sent-to-server")
        query = await client.get("/email-verification?token=not-accepted")
    with Session(migrated_postgresql_engine) as session:
        after = session.scalar(select(text("count(*)")).select_from(Challenge))

    assert before == after
    assert page.status_code == 200
    assert query.status_code == 404
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert "base-uri 'none'" in page.headers["content-security-policy"]
    assert "object-src 'none'" in page.headers["content-security-policy"]
    assert "history.replaceState" in page.text
    assert "addEventListener" in page.text
    assert "Email verified." in page.text
    assert "Verification could not be completed." in page.text
    assert "https://" not in page.text and "http://" not in page.text
    assert "not-sent-to-server" not in page.text


@pytest.mark.anyio
async def test_body_caps_and_validation_errors_never_echo_sensitive_input(
    migrated_postgresql_engine: Engine,
) -> None:
    adapter = RecordingAdapter()
    app = auth_app(migrated_postgresql_engine, adapter)
    password = "SENSITIVE-PASSWORD-DO-NOT-ECHO"
    oversized = b"{" + b'"pad":"' + b"x" * (8 * 1024) + b'"}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        too_large = await client.post(
            "/api/v1/auth/register", content=oversized, headers={"Content-Type": "application/json"}
        )
        invalid = await post(
            client,
            "/api/v1/auth/register",
            {"email": "not-an-email", "password": password},
        )
        form = await client.post(
            "/api/v1/auth/email-verification/resend", data={"email": "x@example.com"}
        )

    assert too_large.status_code == 413
    assert invalid.status_code == 422
    assert form.status_code == 415
    for response in (too_large, invalid, form):
        assert password not in response.text
        assert "not-an-email" not in response.text
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_delivery_runs_after_asgi_response_body_is_sent(
    migrated_postgresql_engine: Engine,
) -> None:
    body_events: list[dict[str, object]] = []
    adapter = RecordingAdapter(body_events)
    app = auth_app(migrated_postgresql_engine, adapter)
    email = f"http-order-{uuid.uuid4()}@example.com"
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/auth/register",
        "raw_path": b"/api/v1/auth/register",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }
    request_body = b'{"email":"' + email.encode() + (
        b'","password":"a sufficiently long registration password"}'
    )
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": request_body, "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        body_events.append(dict(message))

    with cleanup_email(migrated_postgresql_engine, email):
        await app(scope, receive, send)
    assert len(adapter.intents) == 1
