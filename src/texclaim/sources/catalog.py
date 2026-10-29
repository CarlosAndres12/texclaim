"""Resolve cited keys into catalog rows and persist them (PLAN §9 references_catalog)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import texclaim
from texclaim.config import Settings
from texclaim.db.state_store import transaction
from texclaim.parser import ParseResult
from texclaim.parser.bib_parser import BibDatabase
from texclaim.sources.arxiv_client import ArxivClient
from texclaim.sources.budget import RunBudget
from texclaim.sources.global_cache import GlobalCache
from texclaim.sources.http import HttpClient
from texclaim.sources.locator import Locator, SourceResult, SourceValidator
from texclaim.sources.openalex_client import OpenAlexClient


def cited_keys(parsed: ParseResult) -> list[str]:
    return list(dict.fromkeys(c.bib_key for cl in parsed.claims for c in cl.citations))


def make_http(settings: Settings) -> HttpClient:
    ua = f"texclaim/{texclaim.__version__}"
    if settings.contact_email:
        ua += f" (mailto:{settings.contact_email})"
    return HttpClient(ua, offline=settings.offline)


async def resolve_sources(
    paper: Path,
    parsed: ParseResult,
    bibdb: BibDatabase,
    settings: Settings,
    cache: GlobalCache,
    *,
    openalex_key: str | None = None,
    http: HttpClient | None = None,
    validator: SourceValidator | None = None,
    budget: RunBudget | None = None,
) -> tuple[dict[str, SourceResult], RunBudget]:
    """Locate sources for cited keys only (D5). Keys without a usable entry get no cascade."""
    budget = budget or RunBudget(
        settings.sources.openalex_max_usd_per_run, settings.sources.arxiv_max_downloads_per_run
    )
    http = http or make_http(settings)
    openalex = None if settings.offline else OpenAlexClient(http, cache, budget, openalex_key)
    arxiv = None if settings.offline else ArxivClient(http, budget)
    locator = Locator(
        paper, settings, cache, http=http, openalex=openalex, arxiv=arxiv, budget=budget,
        validator=validator,
    )  # fmt: skip
    results: dict[str, SourceResult] = {}
    entries = []
    for key in cited_keys(parsed):
        if key in bibdb.entries:
            entries.append(bibdb.entries[key])
        elif key in bibdb.malformed:
            results[key] = SourceResult(key, "MALFORMED_BIB_ENTRY")
        else:
            results[key] = SourceResult(key, "MISSING_BIB_ENTRY")
    try:
        results.update(await locator.locate_all(entries))
    finally:
        await http.aclose()
    return results, budget


def write_catalog(
    conn: sqlite3.Connection,
    parsed: ParseResult,
    bibdb: BibDatabase,
    results: dict[str, SourceResult],
) -> None:
    with transaction(conn):
        insert_catalog(conn, parsed, bibdb, results)


def insert_catalog(
    conn: sqlite3.Connection,
    parsed: ParseResult,
    bibdb: BibDatabase,
    results: dict[str, SourceResult],
) -> None:
    """Replace references_catalog; the caller owns the transaction."""
    now = datetime.now(UTC).isoformat()
    conn.execute("DELETE FROM references_catalog")
    for key in cited_keys(parsed):
        r = results[key]
        e = bibdb.entries.get(key)
        w = r.work
        conn.execute(
            "INSERT INTO references_catalog(bib_key, bib_file, entry_type, bib_entry_hash,"
            " title, authors_json, year, doi, arxiv_id, pmid, openalex_id, openalex_title,"
            " openalex_year, is_retracted, source_status, source_provider, source_version,"
            " blob_sha256, tei_sha256, text_sha256, source_language, lookup_trail_json,"
            " resolved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                key, e and e.bib_file, e and e.entry_type, e and e.entry_hash,
                e and e.title, json.dumps(e.authors) if e else None, e and e.year,
                e and e.doi, e and e.arxiv_id, e and e.pmid,
                w and w.openalex_id, w and w.title, w and w.year,
                int(w.is_retracted) if w else None,
                r.status, r.provider, r.version, r.blob_sha256, None, None,
                w and w.language,
                json.dumps({"trail": r.trail, "failures": r.failures}), now,
            ),
        )  # fmt: skip


def missing_source_checklist(
    bibdb: BibDatabase, results: dict[str, SourceResult], pdf_dir: str = "papers"
) -> list[dict]:
    """Works lacking full text, with where to drop a PDF."""
    rows = []
    for key, r in results.items():
        if r.status == "FULL_TEXT":
            continue
        e = bibdb.entries.get(key)
        doi = (e.doi if e else None) or (r.work.doi if r.work else None)
        rows.append(
            {
                "key": key,
                "status": r.status,
                "title": (e.title if e else None) or (r.work.title if r.work else None),
                "doi_url": f"https://doi.org/{doi}" if doi else None,
                "landing_page": r.work.landing_page if r.work else None,
                "drop_path": f"{pdf_dir}/{key}.pdf",
            }
        )
    return rows
