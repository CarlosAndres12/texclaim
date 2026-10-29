"""Stages shared by `fetch` and `check`: parse, resolve sources, write the snapshot."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from texclaim import paths
from texclaim.config import Settings, resolve_secret
from texclaim.db.state_store import open_db
from texclaim.parser import ParseResult, parse_manuscript
from texclaim.parser.bib_parser import BibDatabase, parse_bib_files
from texclaim.snapshot import write_snapshot
from texclaim.sources.budget import RunBudget
from texclaim.sources.catalog import resolve_sources
from texclaim.sources.global_cache import GlobalCache
from texclaim.sources.locator import SourceResult


@dataclass
class Prepared:
    parsed: ParseResult
    bibdb: BibDatabase
    results: dict[str, SourceResult]
    budget: RunBudget


def prepare(
    folder: Path,
    settings: Settings,
    *,
    cache_dir: Path | None = None,
    openalex_key: str | None = None,
) -> Prepared:
    folder = folder.resolve()
    parsed = parse_manuscript(folder, settings.main, settings.extra_cite_commands)
    bibdb = parse_bib_files(folder, parsed.root, parsed.bib_resources)
    cache = GlobalCache(paths.global_cache_dir(cache_dir))
    try:
        key = openalex_key or resolve_secret("openalex_api_key")
        results, budget = asyncio.run(
            resolve_sources(folder, parsed, bibdb, settings, cache, openalex_key=key)
        )
    finally:
        cache.close()
    conn = open_db(folder)
    try:
        write_snapshot(conn, parsed, bibdb, results)
    finally:
        conn.close()
    return Prepared(parsed, bibdb, results, budget)
