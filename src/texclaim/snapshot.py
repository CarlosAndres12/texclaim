"""Write the manuscript snapshot tables in one transaction (PLAN §9)."""

from __future__ import annotations

import json
import sqlite3

from texclaim.db.state_store import transaction
from texclaim.parser import ParseResult
from texclaim.parser.bib_parser import BibDatabase
from texclaim.sources.catalog import insert_catalog
from texclaim.sources.locator import SourceResult


def write_snapshot(
    conn: sqlite3.Connection,
    parsed: ParseResult,
    bibdb: BibDatabase,
    results: dict[str, SourceResult],
) -> None:
    """Replace source_files, claims, citations and references_catalog atomically."""
    with transaction(conn):
        conn.execute("DELETE FROM source_files")
        conn.execute("DELETE FROM claims")  # cascades to citations
        for f in [*parsed.files, *bibdb.files]:
            conn.execute(
                "INSERT INTO source_files VALUES (?,?,?,?)",
                (f.path, f.kind, f.sha256, f.size_bytes),
            )
        for c in parsed.claims:
            cur = conn.execute(
                "INSERT INTO claims(claim_hash, file_path, line_start, line_end, char_start,"
                " char_end, section_path, unit_kind, raw_latex, text_norm, context_norm)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    c.claim_hash, c.file_path, c.line_start, c.line_end, c.char_start, c.char_end,
                    c.section_path, c.unit_kind, c.raw_latex, c.text_norm, c.context_norm,
                ),
            )  # fmt: skip
            for k in c.citations:
                conn.execute(
                    "INSERT INTO citations(claim_pk, bib_key, cite_command, prenote, postnote,"
                    " group_keys, attributed_span, unit_key) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        cur.lastrowid, k.bib_key, k.cite_command, k.prenote, k.postnote,
                        json.dumps(k.group_keys), k.attributed_span, k.unit_key,
                    ),
                )  # fmt: skip
        insert_catalog(conn, parsed, bibdb, results)
