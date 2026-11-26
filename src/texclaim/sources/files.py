"""Downloadable files for each cited work: the PDF when we have it, else its text or abstract."""

from __future__ import annotations

import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from texclaim.sources.global_cache import GlobalCache


@dataclass
class SourceFileInfo:
    bib_key: str
    kind: str  # pdf | text | abstract | none
    filename: str | None
    path: Path | None  # on-disk PDF (cache blob)
    text: str | None  # extracted text or abstract (kind text/abstract)
    landing_page: str | None
    doi_url: str | None


def safe_name(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("._") or "source"


def source_text(conn: sqlite3.Connection, text_sha256: str) -> str:
    rows = conn.execute(
        "SELECT page_index, page_label, text FROM source_pages WHERE text_sha256=?"
        " ORDER BY page_index",
        (text_sha256,),
    ).fetchall()
    parts = []
    for r in rows:
        label = f" (printed {r['page_label']})" if r["page_label"] else ""
        parts.append(f"--- page {r['page_index']}{label} ---\n{r['text']}")
    return "\n\n".join(parts)


def source_file(conn: sqlite3.Connection, cache: GlobalCache, bib_key: str) -> SourceFileInfo:
    r = conn.execute("SELECT * FROM references_catalog WHERE bib_key=?", (bib_key,)).fetchone()
    if r is None:
        raise KeyError(bib_key)
    doi_url = f"https://doi.org/{r['doi']}" if r["doi"] else None
    landing = None
    if r["openalex_id"]:
        w = cache.get_work(openalex_id=r["openalex_id"]) or {}
        landing = (w.get("primary_location") or {}).get("landing_page_url") or w.get("doi")
    if r["arxiv_id"] and not landing:
        landing = f"https://arxiv.org/abs/{r['arxiv_id']}"
    name = safe_name(bib_key)
    if r["blob_sha256"]:
        p = cache.get_blob(r["blob_sha256"])
        if p is not None:
            return SourceFileInfo(bib_key, "pdf", f"{name}.pdf", p, None, landing, doi_url)
    if r["text_sha256"]:
        text = source_text(conn, r["text_sha256"])
        kind = "abstract" if r["source_status"] == "ABSTRACT_ONLY" else "text"
        return SourceFileInfo(bib_key, kind, f"{name}.{kind}.txt", None, text, landing, doi_url)
    return SourceFileInfo(bib_key, "none", None, None, None, landing, doi_url)


def export_all(
    conn: sqlite3.Connection, cache: GlobalCache, out_dir: Path, include_self: bool = False
) -> list[SourceFileInfo]:
    out_dir.mkdir(parents=True, exist_ok=True)
    done = []
    keys = [r[0] for r in conn.execute("SELECT bib_key FROM references_catalog ORDER BY bib_key")]
    for key in keys:
        if key == "@self" and not include_self:
            continue
        info = source_file(conn, cache, key)
        if info.kind == "pdf" and info.path:
            shutil.copyfile(info.path, out_dir / info.filename)
        elif info.text is not None and info.filename:
            (out_dir / info.filename).write_text(info.text, encoding="utf-8")
        done.append(info)
    return done
