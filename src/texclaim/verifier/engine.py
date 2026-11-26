"""Run verification units: evidence, model call, validation, persistence (PLAN §10.4, §11)."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from texclaim.config import Settings
from texclaim.models import Unit
from texclaim.planner import claim_language
from texclaim.sources.global_cache import GlobalCache
from texclaim.verifier.evidence import Evidence, build_evidence
from texclaim.verifier.llm_client import ProviderError, Verifier, VerifyRequest
from texclaim.verifier.prompts import build_messages
from texclaim.verifier.validate import finalize
from texclaim.versions import PROMPT_VERSION


@dataclass
class Record:
    origin: str
    verdict: str
    reason_code: str
    evidence_scope: str
    citation_function: str | None = None
    claim_scope: str | None = None
    analysis: str | None = None
    what_is_wrong: str | None = None
    what_source_says: str | None = None
    suggested_fix: str | None = None
    confidence: str | None = None
    evidence: list[dict] = field(default_factory=list)
    needs_review: bool = False
    model: str | None = None
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    raw_response: str | None = None


def deterministic_record(unit: Unit) -> Record:
    """No usable source: UNCHECKABLE with the source status as reason (no LLM call)."""
    reason = unit.source_status
    if reason not in {
        "MISSING_BIB_ENTRY", "MALFORMED_BIB_ENTRY", "NO_SOURCE", "SOURCE_IDENTITY_MISMATCH",
        "SCANNED_PDF", "EXTRACTION_FAILED",
    }:  # fmt: skip
        reason = "EXTRACTION_FAILED"
    return Record("deterministic", "UNCHECKABLE", reason, "none", prompt_version=PROMPT_VERSION)


def store_result(conn: sqlite3.Connection, run_id: str, unit_key: str, r: Record) -> int:
    cur = conn.execute(
        "INSERT INTO verification_results(unit_key, run_id, created_at, origin, verdict,"
        " reason_code, citation_function, evidence_scope, claim_scope, analysis, what_is_wrong,"
        " what_source_says, suggested_fix, confidence, evidence_json, needs_review, model,"
        " prompt_version, input_tokens, output_tokens, cost_usd, raw_response)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            unit_key, run_id, datetime.now(UTC).isoformat(), r.origin, r.verdict, r.reason_code,
            r.citation_function, r.evidence_scope, r.claim_scope, r.analysis, r.what_is_wrong,
            r.what_source_says, r.suggested_fix, r.confidence,
            json.dumps(r.evidence, ensure_ascii=False), int(r.needs_review), r.model,
            r.prompt_version, r.input_tokens, r.output_tokens, r.cost_usd, r.raw_response,
        ),
    )  # fmt: skip
    return cur.lastrowid


class CostBudget:
    """Stops scheduling when spent + in-flight + the next estimate would exceed the cap."""

    def __init__(self, max_usd: float | None) -> None:
        self.max_usd = max_usd
        self.spent = 0.0
        self.reserved = 0.0
        self.completed = 0
        self.unknown_cost_calls = 0

    def estimate(self, initial: float | None = None) -> float:
        if self.completed:
            return self.spent / self.completed
        return initial or 0.0

    def reserve(self, initial: float | None = None) -> float | None:
        est = self.estimate(initial)
        if self.max_usd is not None and self.spent + self.reserved + est > self.max_usd + 1e-12:
            return None
        self.reserved += est
        return est

    def settle(self, est: float, cost: float | None) -> None:
        self.reserved -= est
        self.completed += 1
        if cost is None:
            self.unknown_cost_calls += 1
        else:
            self.spent += cost


async def verify_unit(
    unit: Unit,
    conn: sqlite3.Connection,
    verifier: Verifier,
    settings: Settings,
    *,
    report_language: str = "en",
    cache: GlobalCache | None = None,
) -> Record:
    """One unit end to end. Raises ProviderError if the provider fails or stays unparsable."""
    query = " ".join(
        filter(None, [unit.text_norm, unit.attributed_span, unit.prenote, unit.postnote])
    )
    mlang = claim_language(unit)
    slang = (unit.source_language or "").split("-")[0].lower()
    if unit.strategy == "passages" and slang and slang != mlang:
        terms = cache.get_terms(unit.claim_hash, slang) if cache else None
        if terms is None:
            terms = await verifier.translate(unit.attributed_span or unit.text_norm, slang)
            if cache:
                cache.put_terms(unit.claim_hash, slang, terms)
        query += " " + terms
    ev: Evidence = build_evidence(
        conn,
        strategy=unit.strategy,
        text_sha256=unit.text_sha256,
        query_text=query,
        prenote=unit.prenote,
        postnote=unit.postnote,
        passage_budget_tokens=settings.evidence.passage_budget_tokens,
    )
    if not ev.blocks:
        return Record("deterministic", "UNCHECKABLE", "EXTRACTION_FAILED", "none",
                      prompt_version=PROMPT_VERSION)  # fmt: skip

    in_tok = out_tok = 0
    cost: float | None = None
    raw = ""
    feedback: str | None = None
    schema_ok = getattr(verifier, "supports_schema", True)
    cache_src = bool(getattr(verifier, "is_anthropic", False)) and unit.strategy == "full"
    final = None
    out = None
    for attempt in (1, 2):
        messages = build_messages(
            unit, ev, report_language=report_language, manuscript_language=mlang,
            feedback=feedback, json_schema_in_prompt=not schema_ok, cache_source=cache_src,
        )  # fmt: skip
        call = await verifier.verify(VerifyRequest(unit, ev, messages, report_language, attempt))
        in_tok += call.input_tokens or 0
        out_tok += call.output_tokens or 0
        if call.cost_usd is not None:
            cost = (cost or 0.0) + call.cost_usd
        raw = call.raw
        if call.output is None:
            if attempt == 2:
                raise ProviderError(call.error or "unparsable model output")
            feedback = call.error or "the output was not valid JSON for the schema"
            continue
        out = call.output
        final = finalize(
            out, ev, unit.text_norm if getattr(unit, "origin", "cited") == "internal" else None
        )
        if not final.problems:
            break
        feedback = "; ".join(final.problems)
    assert out is not None and final is not None
    if out.suggested_fix:
        out.suggested_fix = tidy_fix(out.suggested_fix, unit.file_path)
    rec = Record(
        "llm", final.verdict, final.reason_code, ev.scope, out.citation_function, out.claim_scope,
        out.analysis, out.what_is_wrong, out.what_source_says, out.suggested_fix, out.confidence,
        final.quotes, False, getattr(verifier, "model", None), PROMPT_VERSION,
        in_tok, out_tok, cost, raw,
    )  # fmt: skip
    if final.problems:
        rec.needs_review = True
        if final.quote_problem:
            rec.verdict, rec.reason_code = "UNCHECKABLE", "UNVERIFIABLE_EVIDENCE"
            rec.what_is_wrong = rec.what_source_says = rec.suggested_fix = None
        elif rec.verdict == "UNCHECKABLE" and rec.reason_code == "NONE":
            rec.reason_code = "OTHER"
    return rec


@dataclass
class QueueOutcome:
    verified: int = 0
    skipped: int = 0
    errors: int = 0
    budget_exhausted: bool = False
    interrupted: bool = False
    llm_calls: int = 0
    cost_usd: float = 0.0


async def run_queue(
    queue: list[Unit],
    conn: sqlite3.Connection,
    verifier: Verifier,
    settings: Settings,
    *,
    run_id: str,
    budget: CostBudget,
    concurrency: int = 4,
    stop: asyncio.Event | None = None,
    report_language: str = "en",
    cache: GlobalCache | None = None,
    on_result: Callable[[Unit, Record], None] | None = None,
) -> QueueOutcome:
    """Verify units with bounded concurrency; each result is committed as soon as it arrives."""
    out = QueueOutcome()
    sem = asyncio.Semaphore(max(1, concurrency))
    write_lock = asyncio.Lock()
    stop = stop or asyncio.Event()
    estimator = getattr(verifier, "estimate_cost", None)

    async def one(u: Unit) -> None:
        async with sem:
            if stop.is_set():
                out.interrupted = True
                out.skipped += 1
                return
            est = budget.reserve(estimator(u) if estimator else None)
            if est is None:
                out.budget_exhausted = True
                out.skipped += 1
                return
            try:
                rec = await verify_unit(
                    u, conn, verifier, settings, report_language=report_language, cache=cache
                )
            except Exception as e:  # noqa: BLE001 - provider errors are recorded, never cached
                budget.settle(est, 0.0)
                out.errors += 1
                msg = f"{type(e).__name__}: {e}"[:300]
                async with write_lock:
                    conn.execute(
                        "INSERT INTO run_errors VALUES (?,?,?,?,?,?)",
                        (run_id, u.unit_key, "verify", type(e).__name__, msg,
                         datetime.now(UTC).isoformat()),
                    )  # fmt: skip
                return
            budget.settle(est, rec.cost_usd)
            async with write_lock:
                store_result(conn, run_id, u.unit_key, rec)
                out.verified += 1
                out.llm_calls += 1
                out.cost_usd += rec.cost_usd or 0.0
            if on_result:
                on_result(u, rec)

    await asyncio.gather(*(one(u) for u in queue))
    return out


def write_deterministic(conn: sqlite3.Connection, run_id: str, unit: Unit) -> None:
    store_result(conn, run_id, unit.unit_key, deterministic_record(unit))


_BRACKETED_CITE = re.compile(r"\[\s*(\\[A-Za-z]*cite[A-Za-z]*\*?(?:\[[^\]]*\])*\{[^}]*\})\s*\]")


def tidy_fix(fix: str, file_path: str) -> str:
    """Models sometimes wrap LaTeX citation commands in brackets: '[\\cite{x}]' -> '\\cite{x}'."""
    if file_path.endswith(".tex"):
        fix = _BRACKETED_CITE.sub(r"\1", fix)
    return fix
