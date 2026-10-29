"""Deterministic bibliography and source integrity checks (PLAN §13.1)."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from rapidfuzz import fuzz

from texclaim.db.state_store import transaction
from texclaim.parser.bib_parser import arxiv_doi
from texclaim.pipeline import Prepared
from texclaim.sources.identity import norm

SEVERITY = {
    "MISSING_BIB_ENTRY": "error", "MALFORMED_BIB_ENTRY": "error", "DUPLICATE_BIB_KEY": "warning",
    "MISSING_FIELDS": "warning", "DOI_MISMATCH": "error", "METADATA_MISMATCH": "warning",
    "DOI_AVAILABLE": "info", "RETRACTED": "error", "PREPRINT_EVIDENCE": "info",
    "SUSPICIOUS_SOURCE_TEXT": "warning", "SOURCE_IDENTITY_MISMATCH": "warning",
    "UNCITED_ENTRIES": "info",
}  # fmt: skip


@dataclass
class Issue:
    code: str
    severity: str
    detail: str
    bib_key: str | None = None
    file: str | None = None
    line: int | None = None

    @property
    def issue_id(self) -> str:
        raw = f"{self.code}|{self.bib_key}|{self.file}|{self.line}|{self.detail}"
        return "I-" + hashlib.sha256(raw.encode()).hexdigest()[:8]


def compute_integrity(
    prep: Prepared, conn: sqlite3.Connection, *, list_uncited: bool = False
) -> list[Issue]:
    parsed, bibdb, results = prep.parsed, prep.bibdb, prep.results
    first_use: dict[str, tuple[str, int]] = {}
    for c in parsed.claims:
        for cit in c.citations:
            first_use.setdefault(cit.bib_key, (c.file_path, c.line_start))
    nocite = {k for k, *_ in parsed.nocite_keys}
    issues: list[Issue] = []

    for d in [*parsed.diagnostics, *bibdb.diagnostics]:
        issues.append(Issue(d.code, d.severity, d.detail, None, d.file, d.line))

    for key, (f, ln) in first_use.items():
        r = results.get(key)
        e = bibdb.entries.get(key)
        if r is None:
            continue
        if r.status == "MISSING_BIB_ENTRY":
            issues.append(
                Issue("MISSING_BIB_ENTRY", "error", f"no .bib entry for `{key}`", key, f, ln)
            )
            continue
        if r.status == "MALFORMED_BIB_ENTRY":
            issues.append(
                Issue("MALFORMED_BIB_ENTRY", "error", f"`{key}` cannot be parsed", key, f, ln)
            )
            continue
        assert e is not None
        w = r.work
        if e.missing_fields:
            issues.append(
                Issue("MISSING_FIELDS", "warning", f"`{key}` lacks {', '.join(e.missing_fields)}",
                      key, e.bib_file, e.line)
            )  # fmt: skip
        if w and e.doi and w.doi == e.doi and e.title and w.title:
            score = fuzz.token_set_ratio(norm(e.title), norm(w.title))
            if score < 80:
                issues.append(
                    Issue("DOI_MISMATCH", "error",
                          f"DOI {e.doi} resolves to “{w.title}”, not “{e.title}” "
                          f"(match {score:.0f})",
                          key, e.bib_file, e.line)
                )  # fmt: skip
        if w:
            notes = []
            try:
                if e.year and w.year and abs(int(e.year) - int(w.year)) > 1:
                    notes.append(f"year {e.year} vs OpenAlex {w.year}")
            except ValueError:
                pass
            if (
                e.authors
                and w.surnames
                and norm(e.authors[0]["last"]).split()[-1:] != norm(w.surnames[0]).split()[-1:]
            ):
                notes.append(f"first author {e.authors[0]['last']} vs OpenAlex {w.surnames[0]}")
            if notes:
                issues.append(
                    Issue("METADATA_MISMATCH", "warning", "; ".join(notes), key, e.bib_file, e.line)
                )
            if not e.doi and w.doi and w.doi != (arxiv_doi(e.arxiv_id) if e.arxiv_id else None):
                issues.append(
                    Issue(
                        "DOI_AVAILABLE", "info", f"add doi = {{{w.doi}}}", key, e.bib_file, e.line
                    )
                )
            if w.is_retracted:
                issues.append(
                    Issue("RETRACTED", "error", "OpenAlex marks this work as retracted", key, f, ln)
                )
        if r.status == "FULL_TEXT" and r.version == "submittedVersion":
            issues.append(
                Issue(
                    "PREPRINT_EVIDENCE",
                    "info",
                    "evidence taken from a preprint version",
                    key,
                    f,
                    ln,
                )
            )
        if any(x.get("code") == "SOURCE_IDENTITY_MISMATCH" for x in r.failures):
            issues.append(
                Issue("SOURCE_IDENTITY_MISMATCH", "warning",
                      "a file found for this entry is not the cited work (often a wrong DOI)",
                      key, e.bib_file, e.line)
            )  # fmt: skip
        if (
            r.text_sha256
            and conn.execute(
                "SELECT 1 FROM chunks WHERE text_sha256=? AND is_suspicious=1 LIMIT 1",
                (r.text_sha256,),
            ).fetchone()
        ):
            issues.append(
                Issue("SUSPICIOUS_SOURCE_TEXT", "warning",
                      "the source contains instructions aimed at AI readers", key, f, ln)
            )  # fmt: skip

    for key, files in bibdb.duplicates.items():
        if key in first_use or key in nocite:
            issues.append(
                Issue("DUPLICATE_BIB_KEY", "warning",
                      f"`{key}` is defined in {', '.join(dict.fromkeys(files))}; the first wins",
                      key, files[0])
            )  # fmt: skip

    if "*" not in nocite:
        uncited = sorted(set(bibdb.entries) - set(first_use) - nocite)
        if uncited:
            detail = f"{len(uncited)} .bib entries are never cited"
            if list_uncited:
                detail += ": " + ", ".join(uncited)
            issues.append(Issue("UNCITED_ENTRIES", "info", detail))
    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(
        key=lambda i: (order[i.severity], i.code, i.file or "", i.line or 0, i.bib_key or "")
    )
    return issues


def write_integrity(conn: sqlite3.Connection, issues: list[Issue]) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM integrity_issues")
        for i in issues:
            conn.execute(
                "INSERT OR REPLACE INTO integrity_issues VALUES (?,?,?,?,?,?,?)",
                (i.issue_id, i.code, i.severity, i.bib_key, i.file, i.line, i.detail),
            )
