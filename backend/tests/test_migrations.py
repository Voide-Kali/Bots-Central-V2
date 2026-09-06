import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.enums import AccountStatus, AuthenticationLevel, SessionRevocationReason

pytestmark = pytest.mark.postgresql


def test_auth_database_migration_creates_expected_tables(
    migrated_postgresql_engine: Engine,
) -> None:
    table_names = set(inspect(migrated_postgresql_engine).get_table_names())

    assert {
        "users",
        "user_emails",
        "password_credentials",
        "sessions",
        "access_tokens",
        "refresh_tokens",
    }.issubset(table_names)


def test_postgresql_enum_labels_match_python_enum_values(
    migrated_postgresql_engine: Engine,
) -> None:
    expected_values = {
        "account_status": AccountStatus,
        "authentication_level": AuthenticationLevel,
        "session_revocation_reason": SessionRevocationReason,
    }

    with migrated_postgresql_engine.connect() as connection:
        for enum_name, enum_type in expected_values.items():
            labels = connection.scalars(
                text(
                    "SELECT enumlabel FROM pg_enum "
                    "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
                    "WHERE pg_type.typname = :enum_name "
                    "ORDER BY enumsortorder"
                ),
                {"enum_name": enum_name},
            ).all()

            assert labels == [member.value for member in enum_type]
