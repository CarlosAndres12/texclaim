"""Turn located sources into stored, searchable text (PLAN §8 'Reuse')."""

from __future__ import annotations

import sqlite3

from texclaim.db.source_store import store_doc
from texclaim.sources.extractor import Extractor, abstract_doc, extract_cached
from texclaim.sources.global_cache import GlobalCache
from texclaim.sources.locator import SourceResult
from texclaim.text_utils import detect_language


def index_sources(
    conn: sqlite3.Connection,
    results: dict[str, SourceResult],
    cache: GlobalCache,
    extractor: Extractor | None = None,
) -> None:
    """Fill text_sha256 on each result and copy its pages and chunks into the paper DB."""
    for r in results.values():
        doc = None
        if r.status == "FULL_TEXT" and r.blob_sha256:
            path = cache.get_blob(r.blob_sha256)
            if path is None:
                r.status = "EXTRACTION_FAILED"
                continue
            try:
                _, doc = extract_cached(path.read_bytes(), cache, extractor)
            except Exception as e:  # noqa: BLE001
                r.status = "EXTRACTION_FAILED"
                r.failures.append({"code": "EXTRACTION_FAILED", "detail": type(e).__name__})
                continue
        elif r.status == "ABSTRACT_ONLY" and r.abstract:
            doc = abstract_doc(r.abstract)
        if doc is not None:
            r.text_sha256 = store_doc(conn, doc)
            r.language = (
                r.language
                or (r.work.language if r.work else None)
                or detect_language(doc.full_text[:5000])
            )
