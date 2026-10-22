"""Allowlisted JSON events: prompts, model output and upstream errors are never logged."""
import json
import logging
from datetime import datetime, timezone

FIELDS = ("event", "request_id", "status", "error_code", "duration_ms", "requests", "input_tokens", "output_tokens")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"time": datetime.now(timezone.utc).isoformat(), "level": record.levelname}
        data.update({name: getattr(record, name) for name in FIELDS if hasattr(record, name)})
        return json.dumps(data, ensure_ascii=False)


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("deepdive")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # SDK debug logs can include request/response bodies and headers.
    for name in ("openai", "openai.agents", "httpx", "httpx2", "httpcore", "httpcore2"):
        logging.getLogger(name).disabled = True
    return logger
