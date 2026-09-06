import logging
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        connect_args={"connect_timeout": 2},
        pool_pre_ping=True,
    )


def get_session() -> Generator[Session, None, None]:
    session_factory = sessionmaker(bind=get_engine())
    with session_factory() as session:
        yield session


def database_is_available() -> bool:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("Database health check failed")
        return False
