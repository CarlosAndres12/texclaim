"""Stages shared by `fetch` and `check`: parse, resolve sources, write the snapshot."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from texclaim import formats, paths
from texclaim.config import Settings, resolve_secret
from texclaim.db.source_store import gc_sources
from texclaim.db.state_store import open_db
from texclaim.parser import ParseResult, parse_manuscript
from texclaim.parser.bib_parser import BibDatabase, parse_bib_files
from texclaim.snapshot import write_snapshot
from texclaim.sources.budget import RunBudget
from texclaim.sources.catalog import resolve_sources
from texclaim.sources.global_cache import GlobalCache
from texclaim.sources.indexing import index_sources
from texclaim.sources.locator import ExtractingValidator, SourceResult

log = logging.getLogger(__name__)


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
    extractor=None,
    on_stage: Callable[[str], None] | None = None,
) -> Prepared:
    folder = folder.resolve()
    stage = on_stage or (lambda _name: None)
    stage("parse")
    fmt = formats.prepare(folder, settings.main)
    parsed = parse_manuscript(folder, fmt.main, settings.extra_cite_commands)
    formats.remap(fmt, parsed)
    bibdb = parse_bib_files(folder, parsed.root, parsed.bib_resources)
    cache = GlobalCache(paths.global_cache_dir(cache_dir))
    try:
        key = openalex_key or resolve_secret("openalex_api_key")
        stage("resolve, download and extract")
        validator = ExtractingValidator(cache, extractor)
        results, budget = asyncio.run(
            resolve_sources(
                folder, parsed, bibdb, settings, cache, openalex_key=key, validator=validator
            )
        )
        log.debug("resolved %d sources", len(results))
        conn = open_db(folder)
        try:
            index_sources(conn, results, cache, extractor)
            write_snapshot(conn, parsed, bibdb, results)
            gc_sources(conn)
        finally:
            conn.close()
    finally:
        cache.close()
    return Prepared(parsed, bibdb, results, budget)
