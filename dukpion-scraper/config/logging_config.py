"""Structured logging: Rich on the console, JSON lines in logs/scraper.log."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from rich.logging import RichHandler


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(log_dir: Path, level: int = logging.INFO) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    console = RichHandler(rich_tracebacks=True, show_path=False)
    file_h = logging.FileHandler(log_dir / "scraper.log", encoding="utf-8")
    file_h.setFormatter(JsonLineFormatter())
    root.addHandler(console)
    root.addHandler(file_h)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
