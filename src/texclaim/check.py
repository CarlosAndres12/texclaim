"""The `check` pipeline: prepare, plan, verify, resume (PLAN §10)."""

from __future__ import annotations

import asyncio
import json
import signal
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import texclaim
from texclaim import paths
from texclaim.config import ConfigError, Settings
from texclaim.db.state_store import create_run, finish_run, open_db, run_lock
from texclaim.models import Unit
from texclaim.pipeline import Prepared, prepare
from texclaim.planner import is_deterministic, load_units
from texclaim.sources.global_cache import GlobalCache
from texclaim.verifier.engine import CostBudget, QueueOutcome, run_queue, write_deterministic
from texclaim.verifier.llm_client import Verifier

FLAGGED = {"CONTRADICTED", "PARTIALLY_SUPPORTED", "NOT_FOUND"}
GRACE_SECONDS = 10


@dataclass
class CheckOptions:
    force: bool = False
    recheck: str | None = None  # flagged | stale-model
    resume: bool = False
    only_files: list[str] = field(default_factory=list)
    only_keys: list[str] = field(default_factory=list)
    concurrency: int | None = None
    max_cost: float | None = None
    dry_run: bool = False
    report_language: str = "en"
    cache_dir: Path | None = None
    openalex_key: str | None = None
    on_stage: Callable[[str], None] | None = None
    on_result: Callable | None = None
    on_plan: Callable[[int, int], None] | None = None  # (queued, reused)


@dataclass
class CheckOutcome:
    run_id: str | None
    status: str
    prepared: Prepared
    units: list[Unit]
    queue: list[Unit]
    reused: int = 0
    queue_result: QueueOutcome = field(default_factory=QueueOutcome)
    notices: list[str] = field(default_factory=list)
    folder: Path | None = None

    @property
    def incomplete(self) -> bool:
        q = self.queue_result
        return bool(q.errors or q.budget_exhausted or q.interrupted)


def current_result(conn: sqlite3.Connection, unit_key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM current_results WHERE unit_key=?", (unit_key,)).fetchone()


def is_flagged(r: sqlite3.Row) -> bool:
    return r["verdict"] in FLAGGED or bool(r["needs_review"])


def last_resumable(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM runs WHERE status IN ('interrupted','budget_exhausted') "
        "ORDER BY run_id DESC LIMIT 1"
    ).fetchone()


def _selector_matches(sel: dict, r: sqlite3.Row, model: str | None) -> bool:
    if sel.get("force"):
        return True
    if sel.get("recheck") == "flagged":
        return is_flagged(r)
    if sel.get("recheck") == "stale-model":
        return r["origin"] == "llm" and r["model"] != model
    return False


def plan(
    conn: sqlite3.Connection,
    units: list[Unit],
    *,
    selector: dict,
    epoch: str | None,
    model: str | None,
    only_files: list[str],
    only_keys: list[str],
    run_id: str | None,
    write: bool = True,
) -> tuple[list[Unit], int]:
    """The work list: units with no stored result, plus those the selector re-opens."""
    queue: list[Unit] = []
    reused = 0
    for u in units:
        if only_files and u.file_path not in only_files:
            continue
        if only_keys and u.bib_key not in only_keys:
            continue
        r = current_result(conn, u.unit_key)
        if is_deterministic(u):
            if r is None and write and run_id:
                write_deterministic(conn, run_id, u)
            elif r is not None:
                reused += 1
            continue
        if r is None:
            queue.append(u)
        elif r["origin"] == "llm" and r["model"] == "demo" and model not in (None, "demo"):
            queue.append(u)  # demo verdicts are placeholders, never reused by a real model
        elif _selector_matches(selector, r, model) and (epoch is None or r["created_at"] < epoch):
            queue.append(u)
        else:
            reused += 1
    queue.sort(key=lambda u: (u.text_sha256 or "", u.order))
    return queue, reused


def make_verifier(settings: Settings, api_key: str | None = None) -> Verifier:
    from texclaim.config import require_model
    from texclaim.verifier.llm_client import LiteLLMVerifier

    model = require_model(settings)
    if model == "demo":
        from texclaim.verifier.demo import DemoVerifier

        return DemoVerifier()
    if model.startswith("cli:"):
        from texclaim.verifier.cli_agent import CliAgentVerifier
        from texclaim.verifier.llm_client import ProviderError

        try:
            return CliAgentVerifier(model)
        except (ValueError, ProviderError) as e:
            raise ConfigError(str(e)) from e
    return LiteLLMVerifier(model, api_key=api_key)


def install_signal_handlers(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> Callable:
    """First Ctrl+C or SIGTERM stops scheduling; the second exits at once."""

    def handler() -> None:
        if stop.is_set():
            raise KeyboardInterrupt
        stop.set()

    installed = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handler)
            installed.append(sig)
        except (NotImplementedError, RuntimeError):
            pass

    def undo() -> None:
        for sig in installed:
            loop.remove_signal_handler(sig)

    return undo


async def _verify_phase(
    queue, conn, verifier, settings, run_id, opts, budget, stop, cache, handle_signals
) -> QueueOutcome:
    undo = install_signal_handlers(asyncio.get_running_loop(), stop) if handle_signals else None
    try:
        task = asyncio.create_task(
            run_queue(
                queue, conn, verifier, settings,
                run_id=run_id, budget=budget, concurrency=opts.concurrency or 1, stop=stop,
                report_language=opts.report_language, cache=cache, on_result=opts.on_result,
            )
        )  # fmt: skip
        stop_wait = asyncio.create_task(stop.wait())
        await asyncio.wait({task, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
        if not task.done():  # interrupted: give in-flight calls a short grace period
            await asyncio.wait({task}, timeout=GRACE_SECONDS)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                res = QueueOutcome(interrupted=True)
                return res
        stop_wait.cancel()
        return task.result()
    finally:
        if undo:
            undo()


def run_check(
    folder: Path,
    settings: Settings,
    verifier: Verifier | None,
    opts: CheckOptions,
    *,
    extractor=None,
    stop: asyncio.Event | None = None,
    handle_signals: bool = False,
) -> CheckOutcome:
    folder = folder.resolve()
    with run_lock(folder):
        return _run_check_locked(folder, settings, verifier, opts, extractor, stop, handle_signals)


def _run_check_locked(folder, settings, verifier, opts, extractor, stop, handle_signals):
    prep = prepare(
        folder, settings, cache_dir=opts.cache_dir, openalex_key=opts.openalex_key,
        extractor=extractor, on_stage=opts.on_stage,
    )  # fmt: skip
    conn = open_db(folder)
    notices: list[str] = []
    try:
        model = getattr(verifier, "model", None) or settings.model
        ctx = verifier.context_window() if hasattr(verifier, "context_window") else None
        units = load_units(conn, settings, ctx)
        internal_stats = None
        if settings.internal.enabled:
            from texclaim.internal import select_units

            units, internal_stats = select_units(
                conn, units, settings.internal, None if opts.dry_run else verifier
            )
            if internal_stats["candidates"]:
                notices.append(
                    f"internal checks: {internal_stats['kept']} of "
                    f"{internal_stats['candidates']} uncited statements selected for checking"
                )
        if ctx is not None and ctx - 4000 < settings.evidence.full_text_max_tokens:
            notices.append(
                f"model context window ({ctx} tokens) is smaller than full_text_max_tokens "
                f"+ 4000; the full-text budget was lowered for this run"
            )

        from texclaim.reporting.write import resolve_report_language

        opts.report_language = resolve_report_language(settings, [u.text_norm for u in units])
        selector = {"force": opts.force, "recheck": opts.recheck}
        epoch: str | None = None
        if opts.resume:
            prev = last_resumable(conn)
            if prev is None:
                raise ConfigError("no interrupted run to resume")
            saved = json.loads(prev["settings_json"]).get("selector", {})
            selector = {"force": saved.get("force", False), "recheck": saved.get("recheck")}
            epoch = prev["force_epoch"]
        elif opts.force or opts.recheck:
            epoch = datetime.now(UTC).isoformat()

        settings_json = json.dumps({**settings.public_dict(), "selector": selector})
        run_id = None if opts.dry_run else create_run(
            conn, settings_json, model, texclaim.__version__, epoch
        )  # fmt: skip
        queue, reused = plan(
            conn, units, selector=selector, epoch=epoch, model=model,
            only_files=opts.only_files, only_keys=opts.only_keys, run_id=run_id,
            write=not opts.dry_run,
        )  # fmt: skip
        stale = sum(
            1 for u in units
            if (r := current_result(conn, u.unit_key)) is not None
            and r["origin"] == "llm" and r["model"] != model and r["model"] != "demo"
        )  # fmt: skip
        if stale and selector.get("recheck") != "stale-model" and not selector.get("force"):
            notices.append(
                f"{stale} unit(s) were verified with another model and were kept; "
                "use --recheck stale-model to re-verify them"
            )
        outcome = CheckOutcome(
            run_id, "dry-run", prep, units, queue, reused, notices=notices, folder=folder
        )
        if opts.on_plan:
            opts.on_plan(len(queue), reused)
        if opts.dry_run:
            return outcome

        qres = QueueOutcome()
        status = "completed"
        if opts.on_stage:
            opts.on_stage("verify")
        if queue:
            if verifier is None:
                raise ConfigError("no verifier configured")
            budget = CostBudget(
                opts.max_cost if opts.max_cost is not None else settings.budget.max_llm_usd_per_run
            )
            cache = GlobalCache(paths.global_cache_dir(opts.cache_dir))
            try:
                qres = asyncio.run(
                    _verify_phase(
                        queue, conn, verifier, settings, run_id, opts, budget,
                        stop or asyncio.Event(), cache, handle_signals,
                    )
                )  # fmt: skip
            finally:
                cache.close()
            if qres.interrupted:
                status = "interrupted"
            elif qres.budget_exhausted:
                status = "budget_exhausted"
        finish_run(
            conn, run_id, status, qres.llm_calls, qres.cost_usd, prep.budget.openalex_spent
        )  # fmt: skip
        outcome.status, outcome.queue_result = status, qres
        return outcome
    finally:
        conn.close()
