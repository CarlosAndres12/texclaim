"""Post-validation: quotes are matched in code, not trusted (PLAN §11.5, D7)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from texclaim.models import VerifierOutput
from texclaim.verifier.evidence import Block, Evidence

FUZZY_MIN = 90
CLAIM_VERDICTS = {"SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED"}


def normalize_quote(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("­", "")
    s = re.sub(r"(\w)-\s+(?=[a-z])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _flat(block_text: str) -> str:
    """Length-preserving view of a block for matching."""
    flat = block_text.replace("\n", " ").lower()
    return flat if len(flat) == len(block_text) else block_text.replace("\n", " ")


def _norm_id(block_id: str) -> str:
    return re.sub(r"^(?:\[\[)?\s*C\s+", "", block_id.strip().strip("[]")).strip()


@dataclass
class Match:
    block: Block
    start: int
    end: int
    score: float


def _match_in(qn: str, block: Block) -> Match | None:
    bn = _flat(block.text)
    i = bn.find(qn)
    if i >= 0:
        return Match(block, i, i + len(qn), 100.0)
    al = fuzz.partial_ratio_alignment(qn, bn)
    if al is not None and al.score >= FUZZY_MIN:
        return Match(block, al.dest_start, al.dest_end, float(al.score))
    return None


def match_quote(text: str, block_id: str, blocks: list[Block]) -> Match | None:
    """Exact substring in the cited block, then fuzzy in that block, then in all blocks."""
    qn = normalize_quote(text)
    if len(qn) < 8:
        return None
    wanted = _norm_id(block_id)
    cited = [b for b in blocks if b.id == wanted or b.id == block_id.strip()]
    for b in cited:
        m = _match_in(qn, b)
        if m:
            return m
    best = None
    for b in blocks:
        if b in cited:
            continue
        m = _match_in(qn, b)
        if m and (best is None or m.score > best.score):
            best = m
            if m.score == 100.0:
                break
    return best


@dataclass
class Finalized:
    verdict: str
    reason_code: str
    quotes: list[dict]
    needs_review: bool = False
    problems: list[str] = field(default_factory=list)  # reasons a retry may fix
    quote_problem: bool = False


def finalize(out: VerifierOutput, ev: Evidence) -> Finalized:
    """Apply the §11.5 rules to one model answer."""
    verified: list[dict] = []
    problems: list[str] = []
    for i, q in enumerate(out.quotes[:3], 1):
        m = match_quote(q.text, q.block_id, ev.blocks)
        if m is None:
            problems.append(f"quote {i} is not verbatim in [{q.block_id}]")
            continue
        loc = ev.locate(m.block, m.start, m.end)
        verified.append({**loc, "text": m.block.text[m.start : m.end], "score": round(m.score, 1)})
    verdict, reason = out.verdict, out.reason_code
    if verdict == "NOT_FOUND" and ev.scope != "full_text":
        return Finalized("UNCHECKABLE", "INSUFFICIENT_EVIDENCE", verified)
    if verdict in CLAIM_VERDICTS and not verified:
        if not problems:
            problems.append("no quote was provided; copy 1 to 3 verbatim excerpts")
        return Finalized(verdict, reason, verified, problems=problems, quote_problem=True)
    missing = []
    if verdict == "PARTIALLY_SUPPORTED" and not out.what_is_wrong:
        missing.append("what_is_wrong is required for PARTIALLY_SUPPORTED")
    if verdict == "CONTRADICTED":
        if not out.what_is_wrong:
            missing.append("what_is_wrong is required for CONTRADICTED")
        if not out.what_source_says:
            missing.append("what_source_says is required for CONTRADICTED")
    if verdict == "NOT_FOUND" and not out.what_source_says:
        missing.append("what_source_says is required for NOT_FOUND")
    if verdict == "UNCHECKABLE" and reason == "NONE":
        missing.append("reason_code must not be NONE for UNCHECKABLE")
    return Finalized(verdict, reason, verified, problems=missing)


def claim_outcome(verdicts: dict[str, str]) -> dict:
    """Claim-level flags from {bib_key: verdict} for one claim (PLAN §11.5 rule 5)."""
    vs = set(verdicts.values())
    flags = {"contradicted": "CONTRADICTED" in vs, "no_support": False, "padding": []}
    if not vs & {"SUPPORTED", "PARTIALLY_SUPPORTED"} and "NOT_FOUND" in vs:
        flags["no_support"] = True
    if "SUPPORTED" in vs:
        flags["padding"] = [k for k, v in verdicts.items() if v == "NOT_FOUND"]
    return flags
