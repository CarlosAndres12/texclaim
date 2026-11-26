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
    md.write_text(render_markdown(rep, report_language), encoding="utf-8")
    js.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return md, js, rep


REPORT_CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;
margin:2rem auto;
padding:0 1rem;line-height:1.55;color:#1f2328}
h1,h2,h3{line-height:1.25} h3{border-top:1px solid #d0d7de;padding-top:1rem}
blockquote{border-left:4px solid #6366f1;margin:.5rem 0;padding:.25rem 1rem;color:#1f2328;
background:#f6f8fa;border-radius:0 6px 6px 0}
h3{font-size:1.05rem;margin-top:2rem} p{margin:.5rem 0} em{color:#57606a}
table{border-collapse:collapse} td,th{border:1px solid #d0d7de;padding:4px 8px}
code{background:#f6f8fa;padding:1px 4px;border-radius:4px}
"""


def convert_report(md_path: Path, fmt: str, out: Path | None = None) -> Path:
    """Markdown report to html or docx with pandoc."""
    import subprocess

    from texclaim.formats import pandoc_bin

    if fmt not in ("html", "docx"):
        raise ValueError(f"unsupported format: {fmt}")
    out = out or md_path.with_suffix("." + fmt)
    import re

    # Local file:// links to cached PDFs only work on this machine: drop them from exports
    text = md_path.read_text(encoding="utf-8")
    text = re.sub(r" · \[[^\]]+\]\(file://[^)]*\)", "", text)
    text = re.sub(r"\[[^\]]+\]\(file://[^)]*\)", "", text)
    src = md_path.parent / ".texclaim" / "report_export.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(text, encoding="utf-8")
    title = text.splitlines()[0].lstrip("# ").strip() if text else "texclaim"
    args = [pandoc_bin(), str(src), "-f", "gfm", "-o", str(out), "--standalone",
            "--metadata", f"pagetitle={title}"]  # fmt: skip
    if fmt == "html":
        css = md_path.parent / ".texclaim" / "report.css"
        css.write_text(REPORT_CSS, encoding="utf-8")
        args += ["--embed-resources", "--css", str(css)]
    subprocess.run(args, check=True, capture_output=True, timeout=120)
    return out
