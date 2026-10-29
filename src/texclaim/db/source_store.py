"""Source text in the paper DB: pages, chunks, FTS5 index and retrieval (PLAN §8, §9)."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from texclaim.db.state_store import transaction
from texclaim.sources.chunker import chunk_text
from texclaim.sources.extractor import ExtractedDoc
from texclaim.text_utils import content_tokens, tokenize

MAX_QUERY_TOKENS = 40


@dataclass
class ChunkHit:
    chunk_id: str
    score: float  # lower is better for FTS5 bm25; here normalised so higher is better


def has_fts(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='chunk_fts'").fetchone())


def store_doc(conn: sqlite3.Connection, doc: ExtractedDoc) -> str:
    """Copy pages and chunks into the paper DB (idempotent). Returns the text fingerprint."""
    sha = doc.text_sha256
    if conn.execute("SELECT 1 FROM source_pages WHERE text_sha256=? LIMIT 1", (sha,)).fetchone():
        return sha
    chunks = chunk_text(doc.full_text, doc.page_spans, sha)
    fts = has_fts(conn)
    with transaction(conn):
        for p in doc.pages:
            conn.execute(
                "INSERT INTO source_pages VALUES (?,?,?,?)", (sha, p.index, p.label, p.text)
            )
        for c in chunks:
            conn.execute(
                "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    c.chunk_id, sha, c.page_start, c.page_end, c.char_start, c.char_end,
                    c.section_hint, int(c.is_bibliography), int(c.is_suspicious), c.text,
                ),
            )  # fmt: skip
            if fts:
                conn.execute(
                    "INSERT INTO chunk_fts(chunk_id, text_sha256, text) VALUES (?,?,?)",
                    (c.chunk_id, sha, c.text),
                )
    return sha


def gc_sources(conn: sqlite3.Connection) -> None:
    """Delete source text that no catalog entry references any more."""
    live = "SELECT text_sha256 FROM references_catalog WHERE text_sha256 IS NOT NULL"
    with transaction(conn):
        if has_fts(conn):
            conn.execute(f"DELETE FROM chunk_fts WHERE text_sha256 NOT IN ({live})")
        conn.execute(f"DELETE FROM chunks WHERE text_sha256 NOT IN ({live})")
        conn.execute(f"DELETE FROM source_pages WHERE text_sha256 NOT IN ({live})")


def fts_query(text: str) -> str | None:
    """Quote every token and join with OR; raw text never reaches MATCH."""
    toks = content_tokens(text)[:MAX_QUERY_TOKENS]
    return " OR ".join('"' + t.replace('"', "") + '"' for t in toks) if toks else None


def search_chunks(
    conn: sqlite3.Connection,
    text_sha256: str,
    query_text: str,
    limit: int = 20,
    force_bm25: bool = False,
) -> list[ChunkHit]:
    """Top non-bibliography chunks of one source for a claim."""
    q = fts_query(query_text)
    if q is None:
        return []
    if has_fts(conn) and not force_bm25:
        rows = conn.execute(
            "SELECT chunk_fts.chunk_id AS id, bm25(chunk_fts) AS s FROM chunk_fts"
            " JOIN chunks c ON c.chunk_id = chunk_fts.chunk_id"
            " WHERE chunk_fts MATCH ? AND chunk_fts.text_sha256 = ? AND c.is_bibliography = 0"
            " ORDER BY s LIMIT ?",
            (q, text_sha256, limit),
        ).fetchall()
        return [ChunkHit(r["id"], -r["s"]) for r in rows]
    from rank_bm25 import BM25Okapi

    rows = conn.execute(
        "SELECT chunk_id, text FROM chunks WHERE text_sha256=? AND is_bibliography=0"
        " ORDER BY char_start",
        (text_sha256,),
    ).fetchall()
    if not rows:
        return []
    bm = BM25Okapi([tokenize(r["text"]) or ["_"] for r in rows])
    scores = bm.get_scores(re.findall(r'"([^"]+)"', q))
    ranked = sorted(zip(rows, scores, strict=True), key=lambda t: -t[1])
    return [ChunkHit(r["chunk_id"], float(s)) for r, s in ranked[:limit] if s > 0]
