import sqlite3

import pytest
from typer.testing import CliRunner

from texclaim import paths
from texclaim.cli import app
from texclaim.db import state_store
from texclaim.db.state_store import RunLockedError, open_db, run_lock


def test_migrate_from_empty(tmp_path):
    conn = open_db(tmp_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"runs", "claims", "citations", "verification_results", "current_results"} <= tables
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migrate_is_idempotent(tmp_path):
    open_db(tmp_path).close()
    conn = open_db(tmp_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_current_results_view(tmp_path):
    conn = open_db(tmp_path)
    conn.execute(
        "INSERT INTO runs(run_id, started_at, status, settings_json, tool_version) "
        "VALUES ('r','t','running','{}','0')"
    )
    for verdict in ("SUPPORTED", "CONTRADICTED"):
        conn.execute(
            "INSERT INTO verification_results(unit_key, run_id, created_at, origin, verdict,"
            " reason_code, evidence_scope, evidence_json) VALUES ('u','r','t','llm',?,"
            " 'NONE','full_text','[]')",
            (verdict,),
        )
    rows = conn.execute("SELECT verdict FROM current_results").fetchall()
    assert [r[0] for r in rows] == ["CONTRADICTED"]


def test_failed_migration_rolls_back(tmp_path):
    conn = state_store.connect(tmp_path / "x.db")
    conn.executescript("BEGIN; CREATE TABLE t(a); COMMIT;")
    with pytest.raises(sqlite3.Error):
        conn.executescript("BEGIN; CREATE TABLE u(a); CREATE TABLE u(a); COMMIT;")
    conn.execute("ROLLBACK")
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='u'").fetchone()


def test_concurrent_run_refused(tmp_path):
    with run_lock(tmp_path):
        with pytest.raises(RunLockedError):
            with run_lock(tmp_path):
                pass
    with run_lock(tmp_path):  # released afterwards
        pass


def test_init_creates_files(tmp_path):
    r = CliRunner().invoke(app, ["init", str(tmp_path)])
    assert r.exit_code == 0
    assert (paths.paper_state_dir(tmp_path) / ".gitignore").read_text().startswith("*\n")
    assert paths.paper_config_path(tmp_path).exists()
    cfg = paths.paper_config_path(tmp_path)
    cfg.write_text("# mine\n")
    CliRunner().invoke(app, ["init", str(tmp_path)])
    assert cfg.read_text() == "# mine\n"  # never overwritten
