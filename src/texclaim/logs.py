"""Debug logging into .texclaim/logs/, with secrets redacted."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from texclaim import paths

_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+\S+|api[_-]?key['\"=: ]+\S+)", re.I)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SECRET.sub("[redacted]", str(record.getMessage()))
        record.args = ()
        return True


def setup_logging(folder: Path, verbose: bool) -> Path | None:
    if not verbose:
        return None
    logs = paths.paper_logs_dir(folder)
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / f"texclaim-{datetime.now(UTC):%Y%m%dT%H%M%S}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.addFilter(RedactFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    root = logging.getLogger("texclaim")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    return path
