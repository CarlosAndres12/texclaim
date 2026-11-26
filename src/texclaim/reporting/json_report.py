"""Build the report data once; Markdown and JSON are two renderings of it (PLAN §13)."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import texclaim
from texclaim.config import Settings
from texclaim.reporting import suppressions as sup
from texclaim.sources.global_cache import GlobalCache
from texclaim.verifier.validate import claim_outcome
from texclaim.versions import PROMPT_VERSION, REPORT_SCHEMA_VERSION

FLAG_ORDER = {"CONTRADICTED": 0, "PARTIALLY_SUPPORTED": 1, "NOT_FOUND": 2}
FLAGGED = set(FLAG_ORDER)
FIXES = {
    "MISSING_BIB_ENTRY": "add an entry for `{key}` to your .bib file",
    "MALFORMED_BIB_ENTRY": "fix the syntax of the .bib entry for `{key}`",
    "NO_SOURCE": "add `{pdf_dir}/{key}.pdf` (no open-access copy was found)",
    "SOURCE_IDENTITY_MISMATCH": "the file found is not the cited work; check the DOI or add the "
    "right PDF at `{pdf_dir}/{key}.pdf`",
    "SCANNED_PDF": "the PDF has no text layer (OCR is not supported); add a text PDF at "
    "`{pdf_dir}/{key}.pdf`",
    "EXTRACTION_FAILED": "the PDF could not be read; add another copy at `{pdf_dir}/{key}.pdf`",
    "INSUFFICIENT_EVIDENCE": "only the abstract or retrieved passages were available; add the "
    "full PDF at `{pdf_dir}/{key}.pdf` or use --evidence full",
    "UNVERIFIABLE_EVIDENCE": "the model's quotes could not be found in the source; check by hand "
    "or run --recheck flagged",
    "EVIDENCE_IN_FIGURE_OR_TABLE": "the evidence seems to be in a figure or table; check by hand",
    "OFF_TOPIC_SOURCE": "the cited work does not seem related to the claim; check the citation",
    "OTHER": "the model could not decide; check by hand",
    "NONE": "",
}


def _clean_hint(text: str | None) -> str | None:
    if not text:
        return None
    t = _smallcaps(text.strip())
    letters = sum(ch.isalpha() for ch in t)
    if letters < 4 or letters < 0.6 * len(t.replace(" ", "")) or len(t) > 80:
        return None
    if re.search(r"\b(19|20)\d\d\.", t):  # reference-list fragment
        return None
    return t


def _smallcaps(text: str) -> str:
    """'7.2 T EMPORAL AVERAGING' -> '7.2 TEMPORAL AVERAGING' (PDF small caps split words)."""
    return re.sub(r"\b([A-Z]) (?=[A-Z]{2,}\b)", r"\1", text)


def _link(cache: GlobalCache | None, row, page: int | None) -> str | None:
    sha = row["blob_sha256"]
    if cache and sha:
        p = cache.get_blob(sha)
        if p:
            return p.resolve().as_uri() + (f"#page={page}" if page else "")
    if row["doi"]:
        return f"https://doi.org/{row['doi']}"
    if row["openalex_id"]:
        return f"https://openalex.org/{row['openalex_id']}"
    return None


def build_report(
    conn: sqlite3.Connection,
    paper: Path,
    settings: Settings,
    *,
    run_id: str | None = None,
    cache: GlobalCache | None = None,
    notes: list[str] | None = None,
    includeonly: bool = False,
    report_language: str = "en",
    list_uncited: bool = False,
) -> dict:
    run = (
        conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if run_id
        else conn.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    )
    items = sup.load(paper)
    rows = conn.execute(
        "SELECT c.unit_key, c.bib_key, c.cite_command, c.prenote, c.postnote, c.group_keys,"
        " cl.claim_pk, cl.claim_hash, cl.file_path, cl.line_start, cl.line_end, cl.char_start,"
        " cl.char_end, cl.section_path, cl.unit_kind, cl.raw_latex, cl.text_norm, cl.origin AS"
        " claim_origin, cl.role,"
        " res.result_id, res.run_id AS result_run, res.origin, res.verdict, res.reason_code,"
        " res.citation_function, res.evidence_scope, res.claim_scope, res.analysis,"
        " res.what_is_wrong, res.what_source_says, res.suggested_fix, res.confidence,"
        " res.evidence_json, res.needs_review, res.model, res.prompt_version,"
        " r.blob_sha256, r.doi, r.openalex_id, r.source_version, r.text_sha256, r.source_status,"
        " r.source_provider"
        " FROM citations c JOIN claims cl ON cl.claim_pk = c.claim_pk"
        " LEFT JOIN references_catalog r ON r.bib_key = c.bib_key"
        " LEFT JOIN current_results res ON res.unit_key = c.unit_key"
        " ORDER BY cl.claim_pk, c.citation_pk"
    ).fetchall()
    units: dict[str, dict] = {}
    by_claim: dict[int, dict[str, str]] = {}
    claim_loc: dict[int, dict] = {}
    for r in rows:
        if r["verdict"] is None:
            continue
        if r["claim_origin"] != "internal":  # claim-level flags apply to cited claims only
            by_claim.setdefault(r["claim_pk"], {})[r["bib_key"]] = r["verdict"]
        claim_loc.setdefault(
            r["claim_pk"], {"file": r["file_path"], "line": r["line_start"], "text": r["raw_latex"]}
        )
        if r["unit_key"] in units:
            continue
        quotes = []
        for q in json.loads(r["evidence_json"] or "[]"):
            hint = None
            if r["text_sha256"] and r["bib_key"] != "@self":  # @self pages are sections
                h = conn.execute(
                    "SELECT section_hint FROM chunks WHERE text_sha256=? AND char_start<=?"
                    " AND char_end>? ORDER BY char_start DESC LIMIT 1",
                    (r["text_sha256"], q["char_start"], q["char_start"]),
                ).fetchone()
                hint = _clean_hint(h[0]) if h else None
            quotes.append({**q, "section": hint, "link": _link(cache, r, q.get("page"))})
        reason = sup.file_reason(items, r["claim_hash"], r["bib_key"]) or sup.pragma_reason(
            paper, r["file_path"], r["line_start"], r["line_end"], r["bib_key"]
        )
        units[r["unit_key"]] = {
            "id": "F-" + r["unit_key"][:8], "unit_key": r["unit_key"],
            "file": r["file_path"], "line": r["line_start"], "line_end": r["line_end"],
            "char_start": r["char_start"], "char_end": r["char_end"],
            "section": r["section_path"], "unit_kind": r["unit_kind"], "bib_key": r["bib_key"],
            "cite_command": r["cite_command"], "prenote": r["prenote"], "postnote": r["postnote"],
            "claim_latex": r["raw_latex"], "claim_text": r["text_norm"],
            "claim_origin": r["claim_origin"], "role": r["role"],
            "verdict": r["verdict"], "reason_code": r["reason_code"], "origin": r["origin"],
            "evidence_scope": r["evidence_scope"], "citation_function": r["citation_function"],
            "claim_scope": r["claim_scope"], "analysis": r["analysis"],
            "what_is_wrong": r["what_is_wrong"], "what_source_says": r["what_source_says"],
            "suggested_fix": r["suggested_fix"], "confidence": r["confidence"],
            "needs_review": bool(r["needs_review"]), "model": r["model"],
            "prompt_version": r["prompt_version"], "source_version": r["source_version"],
            "source_provider": r["source_provider"], "quotes": quotes,
            "verified_this_run": bool(run)
            and r["result_run"] == run["run_id"]
            and r["origin"] == "llm",
            "suppressed": reason is not None, "suppression_reason": reason,
        }  # fmt: skip
    unit_list = list(units.values())

    findings: list[dict] = []
    for u in sorted(
        (u for u in unit_list if u["verdict"] in FLAGGED), key=lambda u: FLAG_ORDER[u["verdict"]]
    ):
        findings.append({**u, "kind": "unit"})
    for pk, verdicts in by_claim.items():
        flags = claim_outcome(verdicts)
        loc = claim_loc[pk]
        if flags["no_support"]:
            findings.append(
                {"kind": "claim", "id": f"C-{pk}", "flag": "no_support", "file": loc["file"],
                 "line": loc["line"], "claim_latex": loc["text"], "suppressed": False,
                 "detail": "no cited source supports this claim",
                 "keys": sorted(verdicts)}
            )  # fmt: skip
        if flags["padding"]:
            findings.append(
                {"kind": "claim", "id": f"C-{pk}", "flag": "padding", "file": loc["file"],
                 "line": loc["line"], "claim_latex": loc["text"], "suppressed": False,
                 "detail": "possible padding citation: " + ", ".join(flags["padding"]),
                 "keys": flags["padding"]}
            )  # fmt: skip
    for u in unit_list:
        if u["needs_review"] and u["verdict"] not in FLAGGED:
            findings.append({**u, "kind": "unit"})

    issues = []
    for i in conn.execute("SELECT * FROM integrity_issues"):
        issues.append(
            {"id": i["issue_id"], "code": i["code"], "severity": i["severity"],
             "bib_key": i["bib_key"], "file": i["file_path"], "line": i["line"],
             "detail": i["detail"],
             "suppressed": sup.issue_reason(items, i["issue_id"]) is not None}
        )  # fmt: skip
    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: (order[i["severity"]], i["code"], i["file"] or "", i["line"] or 0))

    sources = []
    cov = {"full_text": 0, "abstract_only": 0, "none": 0}
    for r in conn.execute("SELECT * FROM references_catalog ORDER BY bib_key"):
        if r["bib_key"] == "@self":  # the manuscript itself is not a cited work
            continue
        st = r["source_status"]
        cov[
            "full_text"
            if st == "FULL_TEXT"
            else "abstract_only"
            if st == "ABSTRACT_ONLY"
            else "none"
        ] += 1
        sources.append(
            {"bib_key": r["bib_key"], "openalex_id": r["openalex_id"], "doi": r["doi"],
             "title": r["title"], "provider": r["source_provider"], "version": r["source_version"],
             "status": st, "blob_sha256": r["blob_sha256"], "link": _link(cache, r, None)}
        )  # fmt: skip

    models = sorted({u["model"] for u in unit_list if u["model"]})
    this_run = sum(u["verified_this_run"] for u in unit_list)
    n_claims = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    run_info = {
        "run_id": run["run_id"] if run else None,
        "started_at": run["started_at"] if run else None,
        "finished_at": run["finished_at"] if run else None,
        "status": run["status"] if run else None,
        "tool_version": texclaim.__version__,
        "models": models,
        "prompt_version": PROMPT_VERSION,
        "report_language": report_language,
        "llm_calls": run["llm_calls"] if run else 0,
        "llm_cost_usd": run["llm_cost_usd"] if run else 0.0,
        "openalex_cost_usd": run["openalex_cost_usd"] if run else 0.0,
        "counts": {
            "claims": n_claims, "units": len(unit_list), "verified_this_run": this_run,
            "reused": len(unit_list) - this_run,
        },
        "source_coverage": cov,
        "notes": list(notes or []) + (["\\includeonly is ignored: every included file was checked"]
                                       if includeonly else []),
    }  # fmt: skip
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": run_info,
        "findings": findings,
        "units": unit_list,
        "integrity": issues,
        "sources": sources,
        "pdf_dir": settings.pdf_dirs[0] if settings.pdf_dirs else "papers",
        "list_uncited": list_uncited,
    }


def fail_matches(report: dict, fail_on: list[str]) -> list[str]:
    """Unsuppressed findings that match `--fail-on` (verdicts, claim flags, integrity codes)."""
    wanted = {x.strip().lower() for x in fail_on}
    hit = []
    for f in report["findings"]:
        if f["suppressed"]:
            continue
        if f["kind"] == "claim":
            if f["flag"] in wanted:
                hit.append(f["id"])
        elif f["verdict"].lower() in wanted or (f["needs_review"] and "needs_review" in wanted):
            hit.append(f["id"])
    for u in report["units"]:
        if u["verdict"] == "UNCHECKABLE" and not u["suppressed"] and "uncheckable" in wanted:
            hit.append(u["id"])
    for i in report["integrity"]:
        if not i["suppressed"] and i["code"].lower() in wanted:
            hit.append(i["id"])
    return hit
