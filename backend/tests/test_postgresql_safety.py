import pytest
from conftest import require_dedicated_test_database


def test_dedicated_test_database_is_accepted() -> None:
    require_dedicated_test_database("postgresql+psycopg://user:password@localhost/bots_central_test")


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://user:password@localhost/bots_central",
        "postgresql+psycopg://user:password@localhost/production",
        "not-a-database-url",
    ],
)
def test_non_test_database_is_rejected_before_destructive_migrations(database_url: str) -> None:
    with pytest.raises(
        RuntimeError,
        match="Refusing destructive migration test against non-test database",
    ):
        require_dedicated_test_database(database_url)
