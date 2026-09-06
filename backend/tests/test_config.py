import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_invalid_database_url_fails_predictably() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL must be a PostgreSQL URL"):
        Settings(database_url="sqlite:///not-allowed.db")


def test_production_debug_is_rejected() -> None:
    with pytest.raises(ValidationError, match="DEBUG cannot be enabled in production"):
        Settings(app_env="production", debug=True)
