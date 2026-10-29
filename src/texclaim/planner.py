"""Unit keys and the work list (PLAN §10)."""

from __future__ import annotations

import hashlib
import json
import sqlite3

from texclaim.config import Settings
from texclaim.models import Unit
from texclaim.text_utils import detect_language
from texclaim.verifier.evidence import (
    choose_strategy,
    effective_full_max,
    estimate_tokens,
    source_chars,
)
from texclaim.versions import PROMPT_MAJOR

DETERMINISTIC = {
    "MISSING_BIB_ENTRY",
    "MALFORMED_BIB_ENTRY",
    "NO_SOURCE",
    "SOURCE_IDENTITY_MISMATCH",
    "SCANNED_PDF",
    "EXTRACTION_FAILED",
}


def unit_key(
    *,
    claim_hash: str,
    bib_key: str,
    prenote: str | None,
    postnote: str | None,
    group_keys: list[str],
    attributed_span: str,
    source: str,
    strategy: str,
) -> str:
    """Changes exactly when something the verifier would see changes (D1)."""
    payload = {
        "claim": claim_hash,
        "cite": {
            "key": bib_key, "pre": prenote, "post": postnote,
            "group": sorted(group_keys), "span": attributed_span,
        },
        "source": source,  # text hash, or the source status such as "NO_SOURCE"
        "scope": strategy,
        "prompt": PROMPT_MAJOR,
    }  # fmt: skip
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def is_deterministic(u: Unit) -> bool:
    return u.source_status in DETERMINISTIC or (
        u.source_status in ("FULL_TEXT", "ABSTRACT_ONLY") and not u.text_sha256
    )


def load_units(
    conn: sqlite3.Connection,
    settings: Settings,
    context_window: int | None = None,
    write_keys: bool = True,
) -> list[Unit]:
    """Distinct units in manuscript order, with unit keys and evidence strategy."""
    full_max = effective_full_max(settings.evidence.full_text_max_tokens, context_window)
    rows = conn.execute(
        "SELECT c.citation_pk, c.bib_key, c.cite_command, c.prenote, c.postnote, c.group_keys,"
        " c.attributed_span, cl.claim_pk, cl.claim_hash, cl.text_norm, cl.context_norm,"
        " cl.unit_kind, cl.section_path, cl.file_path, cl.line_start,"
        " r.source_status, r.text_sha256, r.source_language, r.source_provider, r.source_version"
        " FROM citations c JOIN claims cl ON cl.claim_pk = c.claim_pk"
        " LEFT JOIN references_catalog r ON r.bib_key = c.bib_key"
        " ORDER BY cl.claim_pk, c.citation_pk"
    ).fetchall()
    keys_by_claim: dict[int, list[str]] = {}
    for r in rows:
        keys_by_claim.setdefault(r["claim_pk"], []).append(r["bib_key"])
    units: dict[str, Unit] = {}
    sizes: dict[str, int] = {}
    updates = []
    for r in rows:
        status = r["source_status"] or "MISSING_BIB_ENTRY"
        sha = r["text_sha256"]
        if sha and sha not in sizes:
            sizes[sha] = estimate_tokens(source_chars(conn, sha))
        strategy = choose_strategy(
            status, sizes.get(sha, 0) if sha else 0, settings.evidence.strategy, full_max
        )
        if sha is None:
            strategy = "none"
        key = unit_key(
            claim_hash=r["claim_hash"], bib_key=r["bib_key"], prenote=r["prenote"],
            postnote=r["postnote"], group_keys=json.loads(r["group_keys"]),
            attributed_span=r["attributed_span"], source=sha or status, strategy=strategy,
        )  # fmt: skip
        updates.append((key, r["citation_pk"]))
        if key in units:
            continue
        units[key] = Unit(
            unit_key=key, bib_key=r["bib_key"], claim_hash=r["claim_hash"],
            text_norm=r["text_norm"], context_norm=r["context_norm"], unit_kind=r["unit_kind"],
            section_path=r["section_path"] or "", file_path=r["file_path"],
            line_start=r["line_start"], cite_command=r["cite_command"], prenote=r["prenote"],
            postnote=r["postnote"], group_keys=json.loads(r["group_keys"]),
            attributed_span=r["attributed_span"],
            other_keys=[
                k for k in dict.fromkeys(keys_by_claim[r["claim_pk"]]) if k != r["bib_key"]
            ],
            source_status=status, text_sha256=sha, source_language=r["source_language"],
            source_provider=r["source_provider"], source_version=r["source_version"],
            strategy=strategy, order=len(units),
        )  # fmt: skip
    if write_keys:
        conn.executemany("UPDATE citations SET unit_key=? WHERE citation_pk=?", updates)
    return list(units.values())


def claim_language(unit: Unit) -> str:
    return detect_language(unit.text_norm)
