"""Machine-wide cache of downloaded files, OpenAlex works and extracted text (PLAN §7.1)."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

WORK_TTL = timedelta(days=30)
NEGATIVE_TTL = timedelta(days=7)
_EXT = {"application/pdf": ".pdf", "application/tei+xml": ".tei.xml"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS blobs(
  sha256 TEXT PRIMARY KEY, size INTEGER NOT NULL, mime TEXT NOT NULL,
  first_url TEXT, fetched_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS identifiers(
  id_type TEXT NOT NULL, id_value TEXT NOT NULL, sha256 TEXT NOT NULL,
  provider TEXT NOT NULL, version TEXT, fetched_at TEXT NOT NULL,
  PRIMARY KEY(id_type, id_value));
CREATE TABLE IF NOT EXISTS openalex_works(
  openalex_id TEXT PRIMARY KEY, doi TEXT, json TEXT NOT NULL, fetched_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS works_by_doi ON openalex_works(doi);
CREATE TABLE IF NOT EXISTS query_terms(
  claim_hash TEXT NOT NULL, language TEXT NOT NULL, terms TEXT NOT NULL,
  PRIMARY KEY(claim_hash, language));
CREATE TABLE IF NOT EXISTS negative(
  id_type TEXT NOT NULL, id_value TEXT NOT NULL, provider TEXT NOT NULL,
  reason TEXT, checked_at TEXT NOT NULL, PRIMARY KEY(id_type, id_value, provider));
"""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(d: datetime) -> str:
    return d.isoformat()


class GlobalCache:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "cache.db", isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(_SCHEMA)

    def close(self) -> None:
        self.db.close()

    # ---- blobs -----------------------------------------------------------------
    def blob_path(self, sha: str, mime: str = "application/pdf") -> Path:
        ext = _EXT.get(mime, ".bin")
        return self.root / "blobs" / "sha256" / sha[:2] / sha[2:4] / f"{sha}{ext}"

    def put_blob(
        self, data: bytes, mime: str = "application/pdf", first_url: str | None = None
    ) -> str:
        sha = hashlib.sha256(data).hexdigest()
        path = self.blob_path(sha, mime)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        self.db.execute(
            "INSERT OR IGNORE INTO blobs VALUES (?,?,?,?,?)",
            (sha, len(data), mime, first_url, _iso(_now())),
        )
        return sha

    def get_blob(self, sha: str) -> Path | None:
        row = self.db.execute("SELECT mime FROM blobs WHERE sha256=?", (sha,)).fetchone()
        if row:
            p = self.blob_path(sha, row["mime"])
            if p.exists():
                return p
        return None

    # ---- identifiers -------------------------------------------------------------
    def set_identifier(
        self, id_type: str, id_value: str, sha: str, provider: str, version: str | None
    ) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO identifiers VALUES (?,?,?,?,?,?)",
            (id_type, id_value.lower(), sha, provider, version, _iso(_now())),
        )

    def lookup_identifier(self, id_type: str, id_value: str) -> sqlite3.Row | None:
        row = self.db.execute(
            "SELECT * FROM identifiers WHERE id_type=? AND id_value=?", (id_type, id_value.lower())
        ).fetchone()
        return row if row and self.get_blob(row["sha256"]) else None

    # ---- OpenAlex works ------------------------------------------------------------
    def put_work(self, work: dict) -> None:
        wid = str(work.get("id", "")).rsplit("/", 1)[-1]
        doi = (work.get("doi") or "").replace("https://doi.org/", "").lower() or None
        self.db.execute(
            "INSERT OR REPLACE INTO openalex_works VALUES (?,?,?,?)",
            (wid, doi, json.dumps(work), _iso(_now())),
        )

    def get_work(self, *, doi: str | None = None, openalex_id: str | None = None) -> dict | None:
        if doi:
            row = self.db.execute(
                "SELECT * FROM openalex_works WHERE doi=?", (doi.lower(),)
            ).fetchone()
        else:
            row = self.db.execute(
                "SELECT * FROM openalex_works WHERE openalex_id=?", (openalex_id,)
            ).fetchone()
        if not row or datetime.fromisoformat(row["fetched_at"]) < _now() - WORK_TTL:
            return None
        return json.loads(row["json"])

    # ---- negative cache --------------------------------------------------------------
    def add_negative(self, id_type: str, id_value: str, provider: str, reason: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO negative VALUES (?,?,?,?,?)",
            (id_type, id_value.lower(), provider, reason, _iso(_now())),
        )

    def is_negative(self, id_type: str, id_value: str, provider: str) -> bool:
        row = self.db.execute(
            "SELECT checked_at FROM negative WHERE id_type=? AND id_value=? AND provider=?",
            (id_type, id_value.lower(), provider),
        ).fetchone()
        return bool(row) and datetime.fromisoformat(row["checked_at"]) > _now() - NEGATIVE_TTL

    # ---- cross-language search terms ------------------------------------------------
    def get_terms(self, claim_hash: str, language: str) -> str | None:
        row = self.db.execute(
            "SELECT terms FROM query_terms WHERE claim_hash=? AND language=?",
            (claim_hash, language),
        ).fetchone()
        return row["terms"] if row else None

    def put_terms(self, claim_hash: str, language: str, terms: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO query_terms VALUES (?,?,?)", (claim_hash, language, terms)
        )

    # ---- extracted text -----------------------------------------------------------------
    def text_path(self, sha: str, extractor_version: int) -> Path:
        return self.root / "text" / f"{sha}.{extractor_version}.json.gz"

    def get_text(self, sha: str, extractor_version: int) -> dict | None:
        p = self.text_path(sha, extractor_version)
        if not p.exists():
            return None
        try:
            return json.loads(gzip.decompress(p.read_bytes()))
        except (OSError, ValueError):
            return None

    def put_text(self, sha: str, extractor_version: int, doc: dict) -> None:
        p = self.text_path(sha, extractor_version)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(gzip.compress(json.dumps(doc).encode()))
        os.replace(tmp, p)

    # ---- maintenance ------------------------------------------------------------------------
    def info(self) -> dict:
        n, size = self.db.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM blobs").fetchone()
        texts = (
            list((self.root / "text").glob("*.json.gz")) if (self.root / "text").exists() else []
        )
        return {
            "path": str(self.root),
            "blobs": n,
            "blob_bytes": size,
            "texts": len(texts),
            "works": self.db.execute("SELECT COUNT(*) FROM openalex_works").fetchone()[0],
        }

    def prune(self, older_than: timedelta | None = None, max_bytes: int | None = None) -> int:
        """Delete oldest blobs (and their extracted text) first. Returns blobs removed."""
        rows = self.db.execute(
            "SELECT sha256, size, mime, fetched_at FROM blobs ORDER BY fetched_at"
        ).fetchall()
        total = sum(r["size"] for r in rows)
        cutoff = _iso(_now() - older_than) if older_than else None
        removed = 0
        for r in rows:
            too_old = cutoff is not None and r["fetched_at"] < cutoff
            too_big = max_bytes is not None and total > max_bytes
            if not (too_old or too_big):
                continue
            self.blob_path(r["sha256"], r["mime"]).unlink(missing_ok=True)
            for t in (self.root / "text").glob(f"{r['sha256']}.*"):
                t.unlink(missing_ok=True)
            self.db.execute("DELETE FROM blobs WHERE sha256=?", (r["sha256"],))
            self.db.execute("DELETE FROM identifiers WHERE sha256=?", (r["sha256"],))
            total -= r["size"]
            removed += 1
        return removed


def parse_age(s: str) -> timedelta:
    """'180d', '12h' -> timedelta."""
    unit = {"d": 86400, "h": 3600, "w": 604800}[s[-1]]
    return timedelta(seconds=int(s[:-1]) * unit)


def parse_size(s: str) -> int:
    mult = {"KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}
    for suffix, m in mult.items():
        if s.upper().endswith(suffix):
            return int(float(s[: -len(suffix)]) * m)
    return int(s)
