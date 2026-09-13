"""HTTP-boundary regression coverage for MVP-1 login and refresh cookies."""

import uuid
from typing import Never

import anyio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.v1.routes import auth as auth_route
from app.auth import authentication
from app.core.config import Settings
from app.main import create_app


class AllowLoginAdmission:
    def admit_login(self, *, canonical_email: str, network: str) -> bool:
        return True


class DenyLoginAdmission:
    def admit_login(self, *, canonical_email: str, network: str) -> bool:
        return False


def unreachable_session_factory() -> Never:
    raise AssertionError("database must not be reached in this boundary test")


def app_with_login_runtime() -> FastAPI:
    settings = Settings(public_origin="http://localhost:8000")
    app = create_app()
    app.state.auth_runtime = auth_route.AuthHttpRuntime(
        session_factory=unreachable_session_factory,
        abuse_controller=AllowLoginAdmission(),  # type: ignore[arg-type]
        keyring=None,
        delivery_adapter=None,
        settings=settings,
        password_limiter=anyio.CapacityLimiter(1),
    )
    return app


@pytest.mark.anyio
async def test_login_requires_same_origin_and_rejects_cross_site_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = app_with_login_runtime()
    called = False

    async def inline_run_sync[T](*args: object, **_: object) -> T:
        operation = args[0]
        assert callable(operation)
        return operation()  # type: ignore[no-any-return]

    def fake_login(*_: object, **__: object) -> authentication.LoginResult:
        nonlocal called
        called = True
        return authentication.LoginResult(
            user_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            access_token=SecretStr("A" * 43),
            refresh_token=SecretStr("B" * 43),
            access_expires_in=600,
        )

    monkeypatch.setattr(authentication, "login", fake_login)
    monkeypatch.setattr(anyio.to_thread, "run_sync", inline_run_sync)
    payload = {"email": "person@example.com", "password": "a" * 15}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        absent = await client.post("/api/v1/auth/login", json=payload)
        cross_site = await client.post(
            "/api/v1/auth/login",
            json=payload,
            headers={"Origin": "http://localhost:8000", "Sec-Fetch-Site": "cross-site"},
        )
        accepted = await client.post(
            "/api/v1/auth/login",
            json=payload,
            headers={"Origin": "http://localhost:8000", "Sec-Fetch-Site": "same-origin"},
        )
    assert absent.status_code == cross_site.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json()["expires_in"] == 600
    assert "refresh_token=" in accepted.headers["set-cookie"]
    assert called


@pytest.mark.anyio
async def test_login_validation_and_body_cap_do_not_echo_secrets() -> None:
    app = app_with_login_runtime()
    password = "sensitive-password-value"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid = await client.post(
            "/api/v1/auth/login",
            json={"email": "not-an-email", "password": password},
            headers={"Origin": "http://localhost:8000"},
        )
        oversized = await client.post(
            "/api/v1/auth/login",
            content=b"x" * (8 * 1024 + 1),
            headers={"Content-Type": "application/json"},
        )
    assert invalid.status_code == 422
    assert oversized.status_code == 413
    assert password not in invalid.text


@pytest.mark.anyio
async def test_login_admission_rejects_before_password_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = app_with_login_runtime()
    app.state.auth_runtime.abuse_controller = DenyLoginAdmission()
    called = False

    def forbidden_login(*_: object, **__: object) -> Never:
        nonlocal called
        called = True
        raise AssertionError("password verification must not run")

    async def inline_run_sync[T](*args: object, **__: object) -> T:
        operation = args[0]
        assert callable(operation)
        return operation()  # type: ignore[no-any-return]

    monkeypatch.setattr(authentication, "login", forbidden_login)
    monkeypatch.setattr(anyio.to_thread, "run_sync", inline_run_sync)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "person@example.com", "password": "a" * 15},
            headers={"Origin": "http://localhost:8000", "Sec-Fetch-Site": "same-origin"},
        )
    assert response.status_code == 429
    assert not called


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/api/v1/auth/refresh", "/api/v1/auth/logout"])
async def test_refresh_and_logout_reject_missing_wrong_or_cross_site_origin(path: str) -> None:
    app = app_with_login_runtime()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post(path)
        wrong = await client.post(path, headers={"Origin": "https://evil.example"})
        cross_site = await client.post(
            path,
            headers={"Origin": "http://localhost:8000", "Sec-Fetch-Site": "cross-site"},
        )
    assert missing.status_code == wrong.status_code == cross_site.status_code == 403


@pytest.mark.anyio
async def test_same_origin_refresh_and_logout_pass_csrf_boundary() -> None:
    app = app_with_login_runtime()
    headers = {"Origin": "http://localhost:8000", "Sec-Fetch-Site": "same-origin"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        refresh = await client.post("/api/v1/auth/refresh", headers=headers)
        logout = await client.post("/api/v1/auth/logout", headers=headers)
    assert refresh.status_code == 401
    assert logout.status_code == 204


@pytest.mark.anyio
async def test_login_failure_does_not_echo_or_log_password(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    app = app_with_login_runtime()
    password = "sensitive-password-value"

    def failing_login(*_: object, **__: object) -> Never:
        raise RuntimeError(password)

    async def inline_run_sync[T](*args: object, **_: object) -> T:
        operation = args[0]
        assert callable(operation)
        return operation()  # type: ignore[no-any-return]

    monkeypatch.setattr(authentication, "login", failing_login)
    monkeypatch.setattr(anyio.to_thread, "run_sync", inline_run_sync)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "person@example.com", "password": password},
            headers={"Origin": "http://localhost:8000"},
        )
    assert response.status_code == 503
    assert password not in response.text
    assert password not in caplog.text


@pytest.mark.anyio
async def test_invalid_token_responses_do_not_echo_or_log_token_material(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    app = app_with_login_runtime()
    access_token = "C" * 43
    refresh_token = "D" * 43
    access_digest = "access-digest-marker"
    refresh_digest = "refresh-digest-marker"

    def invalid_access(*_: object, **__: object) -> Never:
        raise authentication.InvalidAccessToken

    def invalid_refresh(*_: object, **__: object) -> authentication.RefreshResult:
        return authentication.RefreshResult(False)

    async def inline_run_sync[T](*args: object, **_: object) -> T:
        operation = args[0]
        assert callable(operation)
        return operation()  # type: ignore[no-any-return]

    monkeypatch.setattr(authentication, "authenticate_access", invalid_access)
    monkeypatch.setattr(authentication, "refresh", invalid_refresh)
    monkeypatch.setattr(anyio.to_thread, "run_sync", inline_run_sync)
    headers = {"Origin": "http://localhost:8000", "Sec-Fetch-Site": "same-origin"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        me = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
        )
        client.cookies.set("refresh_token", refresh_token, path="/api/v1/auth")
        refresh = await client.post("/api/v1/auth/refresh", headers=headers)
    assert me.status_code == refresh.status_code == 401
    for secret in (access_token, refresh_token, access_digest, refresh_digest):
        assert secret not in me.text
        assert secret not in refresh.text
        assert secret not in caplog.text
