"""Suppressions: reviewed, committable, keyed by (claim_hash, bib_key) (PLAN §13.3)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import tomli_w

from texclaim import paths

_PRAGMA = re.compile(r"%\s*texclaim:\s*ignore\[([^\]]*)\]\s*(.*)$")


@dataclass
class Suppression:
    reason: str
    date: str
    claim_hash: str | None = None
    bib_key: str | None = None
    issue: str | None = None  # integrity issue id, e.g. I-1a2b3c4d


def load(paper: Path) -> list[Suppression]:
    p = paths.paper_suppressions_path(paper)
    if not p.exists():
        return []
    with p.open("rb") as f:
        data = tomllib.load(f)
    return [
        Suppression(
            reason=e.get("reason", ""), date=e.get("date", ""), claim_hash=e.get("claim_hash"),
            bib_key=e.get("bib_key"), issue=e.get("issue"),
        )
        for e in data.get("suppress", [])
    ]  # fmt: skip


def _save(paper: Path, items: list[Suppression]) -> None:
    p = paths.paper_suppressions_path(paper)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = [{k: v for k, v in vars(s).items() if v is not None} for s in items]
    p.write_text(tomli_w.dumps({"suppress": rows}), encoding="utf-8")


def add(paper: Path, reason: str, *, claim_hash=None, bib_key=None, issue=None) -> None:
    items = load(paper)
    items = [s for s in items if not _same(s, claim_hash, bib_key, issue)]
    items.append(
        Suppression(reason, datetime.now(UTC).date().isoformat(), claim_hash, bib_key, issue)
    )
    _save(paper, items)


def remove(paper: Path, *, claim_hash=None, bib_key=None, issue=None) -> bool:
    items = load(paper)
    kept = [s for s in items if not _same(s, claim_hash, bib_key, issue)]
    if len(kept) != len(items):
        _save(paper, kept)
    return len(kept) != len(items)


def _same(s: Suppression, claim_hash, bib_key, issue) -> bool:
    if issue:
        return s.issue == issue
    return s.claim_hash == claim_hash and s.bib_key == bib_key


def file_reason(items: list[Suppression], claim_hash: str, bib_key: str) -> str | None:
    for s in items:
        if s.claim_hash == claim_hash and s.bib_key == bib_key:
            return s.reason or "suppressed"
    return None


def issue_reason(items: list[Suppression], issue_id: str) -> str | None:
    for s in items:
        if s.issue == issue_id:
            return s.reason or "suppressed"
    return None


def pragma_reason(
    paper: Path, file_path: str, line_start: int, line_end: int, bib_key: str
) -> str | None:
    """`% texclaim: ignore[key] reason` on a line of the claim or the line above."""
    try:
        lines = (paper / file_path).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None
    for n in range(max(1, line_start - 1), min(len(lines), line_end) + 1):
        m = _PRAGMA.search(lines[n - 1])
        if m and bib_key in [k.strip() for k in m.group(1).split(",")]:
            return m.group(2).strip() or "inline pragma"
    return None
