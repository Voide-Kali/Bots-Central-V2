import asyncio
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.routes import health as health_route
from app.main import create_app


async def run_synchronously_for_test(function: Callable[[], bool]) -> bool:
    return function()


def test_application_initializes() -> None:
    assert create_app().title == "Bots Central V2"


@pytest.mark.anyio
async def test_health_returns_unavailable_database(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_route, "database_is_available", lambda: False)
    monkeypatch.setattr(asyncio, "to_thread", run_synchronously_for_test)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "status": "degraded",
        "application": "Bots Central V2",
        "database": "unavailable",
    }


@pytest.mark.anyio
async def test_health_returns_connected_database(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_route, "database_is_available", lambda: True)
    monkeypatch.setattr(asyncio, "to_thread", run_synchronously_for_test)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "status": "ok",
        "application": "Bots Central V2",
        "database": "connected",
    }
