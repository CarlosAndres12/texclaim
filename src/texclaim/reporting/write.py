"""Write texclaim_report.md / .json for a finished check (PLAN §13)."""

from __future__ import annotations

import json
from pathlib import Path

from texclaim import paths
from texclaim.config import Settings
from texclaim.db.state_store import open_db
from texclaim.reporting.integrity import compute_integrity, write_integrity
from texclaim.reporting.json_report import build_report
from texclaim.reporting.markdown import render_markdown
from texclaim.sources.global_cache import GlobalCache
from texclaim.text_utils import detect_language

REPORT_MD = "texclaim_report.md"
REPORT_JSON = "texclaim_report.json"


def resolve_report_language(settings: Settings, claim_texts: list[str]) -> str:
    """'auto' follows the manuscript: Spanish when most cited claims are Spanish."""
    if settings.report_language != "auto":
        return settings.report_language
    es = sum(detect_language(t) == "es" for t in claim_texts)
    return "es" if claim_texts and es * 2 > len(claim_texts) else "en"


def write_reports(
    folder: Path,
    settings: Settings,
    outcome,
    *,
    report_dir: Path | None = None,
    cache_dir: Path | None = None,
    list_uncited: bool = False,
    report_language: str = "en",
) -> tuple[Path, Path, dict]:
    conn = open_db(folder)
    cache = GlobalCache(paths.global_cache_dir(cache_dir))
    try:
        write_integrity(conn, compute_integrity(outcome.prepared, conn, list_uncited=list_uncited))
        rep = build_report(
            conn, folder, settings, run_id=outcome.run_id, cache=cache, notes=outcome.notices,
            includeonly=outcome.prepared.parsed.includeonly, report_language=report_language,
            list_uncited=list_uncited,
        )  # fmt: skip
    finally:
        cache.close()
        conn.close()
    out = Path(report_dir) if report_dir else folder
    out.mkdir(parents=True, exist_ok=True)
    md, js = out / REPORT_MD, out / REPORT_JSON
    md.write_text(render_markdown(rep), encoding="utf-8")
    js.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return md, js, rep
