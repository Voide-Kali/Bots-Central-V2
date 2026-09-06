import logging

from app.core.logging import RedactingFilter


def test_logging_redacts_common_credentials() -> None:
    logger = logging.getLogger("tests.logging")
    record = logger.makeRecord(
        logger.name,
        logging.WARNING,
        __file__,
        1,
        (
            "password=plain token: abc Authorization: Bearer-value API key=key-value "
            "postgresql+psycopg://user:db-password@db:5432/bots_central"
        ),
        (),
        None,
    )

    assert RedactingFilter().filter(record)
    message = record.getMessage()
    for secret in ("plain", "abc", "Bearer-value", "key-value", "db-password"):
        assert secret not in message
    assert "[REDACTED]" in message
