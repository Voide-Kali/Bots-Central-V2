from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from alembic import command
from app.db.enums import (
    AccountStatus,
    AuthenticationLevel,
    EmailVerificationInvalidationReason,
    EmailVerificationMaterialType,
    SessionRevocationReason,
)

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
        "email_verification_challenges",
    }.issubset(table_names)


def test_postgresql_enum_labels_match_python_enum_values(
    migrated_postgresql_engine: Engine,
) -> None:
    expected_values = {
        "account_status": AccountStatus,
        "authentication_level": AuthenticationLevel,
        "session_revocation_reason": SessionRevocationReason,
        "email_verification_material_type": EmailVerificationMaterialType,
        "email_verification_invalidation_reason": EmailVerificationInvalidationReason,
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


def test_email_verification_constraints_and_indexes_are_real_postgresql_catalog_entries(
    migrated_postgresql_engine: Engine,
) -> None:
    with migrated_postgresql_engine.connect() as connection:
        constraints: dict[str, str] = {
            str(name): str(definition)
            for name, definition in connection.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(pg_constraint.oid, true) "
                    "FROM pg_constraint "
                    "JOIN pg_class ON pg_class.oid = pg_constraint.conrelid "
                    "WHERE pg_class.relname = 'email_verification_challenges' "
                    "AND contype = 'c'"
                )
            ).tuples()
        }
        indexes: dict[str, str] = {
            str(name): str(definition)
            for name, definition in connection.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename = 'email_verification_challenges'"
                )
            ).tuples()
        }

    material_definition = constraints["ck_email_verification_material_fields"]
    normalized_material_definition = material_definition.replace("::character varying", "").replace(
        "::text", ""
    )
    assert "expires_at > created_at" in constraints["ck_email_verification_expires_after_created"]
    assert "consumed_at IS NOT NULL AND invalidated_at IS NOT NULL" in constraints[
        "ck_email_verification_terminal_states_exclusive"
    ]
    assert "invalidated_at IS NULL AND invalidation_reason IS NULL" in constraints[
        "ck_email_verification_invalidation_state"
    ]
    for fragment in (
        "material_type = 'link'",
        "link_token_digest IS NOT NULL",
        "octet_length(link_token_digest) = 32",
        "code_digest IS NULL",
        "hmac_key_version IS NULL",
        "attempt_count IS NULL",
        "max_attempts IS NULL",
        "material_type = 'code'",
        "link_token_digest IS NULL",
        "code_digest IS NOT NULL",
        "octet_length(code_digest) = 32",
        "hmac_key_version IS NOT NULL",
        "hmac_key_version <> ''",
        "max_attempts IS NOT NULL",
        "max_attempts = 5",
        "attempt_count IS NOT NULL",
        "attempt_count >= 0",
        "attempt_count <= 5",
    ):
        assert fragment in normalized_material_definition

    assert "UNIQUE" in indexes["email_verification_challenges_pkey"]
    assert "UNIQUE" in indexes["uq_email_verification_link_token_digest"]
    assert "WHERE (link_token_digest IS NOT NULL)" in indexes[
        "uq_email_verification_link_token_digest"
    ]
    assert "(user_email_id)" in indexes["ix_email_verification_challenges_user_email_id"]
    assert "(user_email_id, created_at DESC)" in indexes[
        "ix_email_verification_challenges_user_email_created_at"
    ]
    assert not any("code_digest" in definition for definition in indexes.values())


def test_email_verification_migration_downgrades_and_upgrades_again(
    migrated_postgresql_engine: Engine,
) -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.downgrade(config, "0002_auth_database_foundation")
    with migrated_postgresql_engine.connect() as connection:
        table_names = set(inspect(connection).get_table_names())
        enum_names = set(
            connection.scalars(
                text(
                    "SELECT typname FROM pg_type "
                    "JOIN pg_namespace ON pg_namespace.oid = pg_type.typnamespace "
                    "WHERE nspname = 'public'"
                )
            )
        )
    assert "email_verification_challenges" not in table_names
    assert "email_verification_material_type" not in enum_names
    assert "email_verification_invalidation_reason" not in enum_names

    command.upgrade(config, "head")
    with migrated_postgresql_engine.connect() as connection:
        assert "email_verification_challenges" in set(inspect(connection).get_table_names())
