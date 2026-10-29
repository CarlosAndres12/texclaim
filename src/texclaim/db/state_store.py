"""Per-paper SQLite state: connections, migrations and the run lock (PLAN §9)."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from filelock import FileLock, Timeout

from texclaim import paths
from texclaim.config import ConfigError

_MIGRATION_NAME = re.compile(r"^(\d{4})_[\w]+\.sql$")


class RunLockedError(ConfigError):
    """Another texclaim run holds the lock on this paper folder."""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def fts5_available(conn: sqlite3.Connection | None = None) -> bool:
    own = conn is None
    conn = conn or sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE temp._fts_probe USING fts5(x)")
        conn.execute("DROP TABLE temp._fts_probe")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        if own:
            conn.close()


def _migrations() -> list[tuple[int, str, str]]:
    found = []
    for entry in resources.files("texclaim.db.migrations").iterdir():
        m = _MIGRATION_NAME.match(entry.name)
        if m:
            found.append((int(m.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    return sorted(found)


def migrate(conn: sqlite3.Connection) -> int:
    """Apply migrations above PRAGMA user_version, each in one transaction."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    has_fts = fts5_available(conn)
    for version, name, sql in _migrations():
        if version <= current:
            continue
        if not has_fts:  # bm25 fallback is used in memory; skip the FTS5 table
            sql = re.sub(r"CREATE VIRTUAL TABLE[^;]*USING fts5[^;]*;", "", sql, flags=re.S)
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
        except sqlite3.Error as e:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise RuntimeError(f"migration {name} failed: {e}") from e
        current = version
    return current


def open_db(paper: Path) -> sqlite3.Connection:
    conn = connect(paths.paper_db_path(paper))
    migrate(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


@contextmanager
def run_lock(paper: Path) -> Iterator[None]:
    lock_path = paths.paper_lock_path(paper)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_path), timeout=0)
    try:
        lock.acquire()
    except Timeout as e:
        raise RunLockedError(f"another texclaim run is active on {paper} ({lock_path})") from e
    try:
        yield
    finally:
        lock.release()


_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    import os
    import time

    n = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(_B32[(n >> (5 * i)) & 31] for i in range(25, -1, -1))


def create_run(
    conn: sqlite3.Connection,
    settings_json: str,
    model: str | None,
    tool_version: str,
    force_epoch: str | None = None,
) -> str:
    from datetime import UTC, datetime

    run_id = new_ulid()
    conn.execute(
        "INSERT INTO runs(run_id, started_at, status, settings_json, force_epoch, tool_version,"
        " model) VALUES (?,?,?,?,?,?,?)",
        (run_id, datetime.now(UTC).isoformat(), "running", settings_json, force_epoch,
         tool_version, model),
    )  # fmt: skip
    return run_id


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
    llm_calls: int = 0,
    llm_cost: float = 0.0,
    openalex_cost: float = 0.0,
) -> None:
    from datetime import UTC, datetime

    conn.execute(
        "UPDATE runs SET status=?, finished_at=?, llm_calls=?, llm_cost_usd=?,"
        " openalex_cost_usd=? WHERE run_id=?",
        (status, datetime.now(UTC).isoformat(), llm_calls, llm_cost, openalex_cost, run_id),
    )
