"""Dedicated PostgreSQL regression for the uncommitted Device migration."""

from pathlib import Path

import pytest
from alembic.config import Config
from conftest import require_dedicated_test_database
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url

from alembic import command
from app.core.config import get_settings

pytestmark = pytest.mark.postgresql

_REVOKED_AT_EXISTS = text(
    "SELECT EXISTS ("
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_name = 'device_pairing_tokens' AND column_name = 'revoked_at'"
    ")"
)


def _catalog(engine: Engine) -> tuple[bool, bool]:
    with engine.connect() as connection:
        devices = connection.scalar(text("SELECT to_regclass('public.devices') IS NOT NULL"))
        lifecycle_type = connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'device_lifecycle_status')")
        )
    return bool(devices), bool(lifecycle_type)


def _revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    if revision is None or isinstance(revision, str):
        return revision
    raise AssertionError("alembic_version returned an unexpected value")


def _assert_engine_target(engine: Engine, expected_url: URL) -> None:
    assert engine.url.database == expected_url.database
    assert engine.url.host == expected_url.host
    assert engine.url.port == expected_url.port
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT current_database()")) == expected_url.database


def test_device_migration_roundtrip_0004_0005(
    migrated_postgresql_engine: Engine,
    postgresql_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_dedicated_test_database(postgresql_database_url)
    expected_url = make_url(postgresql_database_url)
    assert expected_url.database == "bots_central_test"
    try:
        with monkeypatch.context() as environment:
            environment.setenv("DATABASE_URL", postgresql_database_url)
            get_settings.cache_clear()
            config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
            config.set_main_option("sqlalchemy.url", postgresql_database_url)
            configured_url = config.get_main_option("sqlalchemy.url")
            assert configured_url is not None
            assert make_url(get_settings().database_url) == expected_url
            assert make_url(configured_url) == expected_url
            _assert_engine_target(migrated_postgresql_engine, expected_url)

            command.downgrade(config, "0004_auth_abuse_control")
            assert _revision(migrated_postgresql_engine) == "0004_auth_abuse_control"
            assert _catalog(migrated_postgresql_engine) == (False, False)

            command.upgrade(config, "0005_device_foundation")
            assert _revision(migrated_postgresql_engine) == "0005_device_foundation"
            assert _catalog(migrated_postgresql_engine) == (True, True)

            command.upgrade(config, "0006_device_online_v01")
            assert _revision(migrated_postgresql_engine) == "0006_device_online_v01"
            with migrated_postgresql_engine.connect() as connection:
                assert connection.scalar(
                    text("SELECT to_regclass('public.device_pairing_tokens') IS NOT NULL")
                )

            command.upgrade(config, "0007_pairing_revocation")
            assert _revision(migrated_postgresql_engine) == "0007_pairing_revocation"
            with migrated_postgresql_engine.connect() as connection:
                assert connection.scalar(_REVOKED_AT_EXISTS)
            command.downgrade(config, "0006_device_online_v01")
            assert _revision(migrated_postgresql_engine) == "0006_device_online_v01"
            with migrated_postgresql_engine.connect() as connection:
                assert not connection.scalar(_REVOKED_AT_EXISTS)
            command.upgrade(config, "0007_pairing_revocation")
            assert _revision(migrated_postgresql_engine) == "0007_pairing_revocation"

            command.downgrade(config, "0005_device_foundation")
            assert _revision(migrated_postgresql_engine) == "0005_device_foundation"
            with migrated_postgresql_engine.connect() as connection:
                assert connection.scalar(
                    text("SELECT to_regclass('public.device_pairing_tokens') IS NULL")
                )

            command.downgrade(config, "0004_auth_abuse_control")
            assert _revision(migrated_postgresql_engine) == "0004_auth_abuse_control"
            assert _catalog(migrated_postgresql_engine) == (False, False)

            command.upgrade(config, "0005_device_foundation")
            assert _revision(migrated_postgresql_engine) == "0005_device_foundation"
            assert _catalog(migrated_postgresql_engine) == (True, True)
    finally:
        get_settings.cache_clear()
