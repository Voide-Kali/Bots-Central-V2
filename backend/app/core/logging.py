import logging
import re

DATABASE_CREDENTIALS = re.compile(r"(postgres(?:ql)?(?:\+[\w]+)?://)([^\s/@:]+):([^\s/@]+)@")
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(password|token|secret|api(?:[_ -]?key)|authorization)\b\s*[:=]\s*[^\s,]+"
)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        message = DATABASE_CREDENTIALS.sub(r"\1[REDACTED]:[REDACTED]@", message)
        message = SENSITIVE_ASSIGNMENT.sub(r"\1=[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


def configure_logging(log_level: str) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    if root_logger.handlers:
        for handler in root_logger.handlers:
            handler.addFilter(RedactingFilter())
        return

    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root_logger.addHandler(handler)
