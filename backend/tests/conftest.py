import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import get_settings
from app.db.session import get_engine
from app.main import create_app


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Generator[None, None, None]:
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture
def app() -> FastAPI:
    return create_app()


def require_dedicated_test_database(database_url: str) -> None:
    try:
        database_name = make_url(database_url).database
    except Exception as error:
        raise RuntimeError(
            "Refusing destructive migration test against non-test database"
        ) from error
    if database_name != "bots_central_test":
        raise RuntimeError("Refusing destructive migration test against non-test database")


@pytest.fixture(scope="session")
def postgresql_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return database_url


@pytest.fixture(scope="session")
def migrated_postgresql_engine(postgresql_database_url: str) -> Generator[Engine, None, None]:
    require_dedicated_test_database(postgresql_database_url)
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = postgresql_database_url
    get_settings.cache_clear()

    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(postgresql_database_url)

    try:
        yield engine
    finally:
        command.downgrade(config, "0001_foundation")
        command.upgrade(config, "head")
        engine.dispose()
        if previous_database_url is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        get_settings.cache_clear()


@pytest.fixture
def postgresql_session(migrated_postgresql_engine: Engine) -> Generator[Session, None, None]:
    connection = migrated_postgresql_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
