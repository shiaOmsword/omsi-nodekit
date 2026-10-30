import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar

_context: ContextVar[dict[str, str]] = ContextVar("log_context", default={})


def log_context() -> dict[str, str]:
    return _context.get().copy()


@contextmanager
def bind_context(**fields):
    token = _context.set({**_context.get(), **{k: str(v) for k, v in fields.items()}})
    try:
        yield
    finally:
        _context.reset(token)


class ContextJsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **log_context(),
        }
        for key in ("method", "path", "status", "duration_ms", "error_code", "error_type"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        # Request bodies, exception values, process payloads and passwords are never serialized.
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str):
    logger = logging.getLogger("nodekit")
    logger.setLevel(level.upper())
    if not any(getattr(handler, "nodekit_handler", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.nodekit_handler = True
        handler.setFormatter(ContextJsonFormatter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger
