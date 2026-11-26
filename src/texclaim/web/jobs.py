"""Background check runs for the web app, with an event log the browser follows over SSE."""

from __future__ import annotations

import asyncio
import threading
import time
import traceback
from dataclasses import dataclass, field

from texclaim.web.projects import Project, ProjectStore


class ThreadStop(asyncio.Event):
    """An asyncio.Event that another thread can set (polled; set() is not loop-bound)."""

    def __init__(self) -> None:
        super().__init__()
        self.flag = threading.Event()

    def is_set(self) -> bool:  # type: ignore[override]
        return self.flag.is_set()

    def set(self) -> None:  # type: ignore[override]
        self.flag.set()

    async def wait(self) -> bool:  # type: ignore[override]
        while not self.flag.is_set():
            await asyncio.sleep(0.2)
        return True


@dataclass
class Job:
    project_id: str
    kind: str = "check"
    state: str = "running"  # running | done | failed | cancelled
    events: list[dict] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    stop: ThreadStop = field(default_factory=ThreadStop)
    total: int = 0
    done: int = 0
    cost: float = 0.0
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, type_: str, **data) -> None:
        with self.lock:
            self.events.append({"seq": len(self.events), "type": type_, "t": time.time(), **data})

    def snapshot(self) -> dict:
        return {
            "project_id": self.project_id, "kind": self.kind, "state": self.state,
            "total": self.total, "done": self.done, "cost": round(self.cost, 6),
            "error": self.error, "started": self.started, "events": len(self.events),
        }  # fmt: skip


class JobManager:
    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def current(self, pid: str) -> Job | None:
        return self.jobs.get(pid)

    def start(self, project: Project, *, force: bool = False, dry_run: bool = False) -> Job:
        with self._lock:
            j = self.jobs.get(project.id)
            if j and j.state == "running":
                raise RuntimeError("a run is already in progress for this project")
            job = Job(project.id)
            self.jobs[project.id] = job
        t = threading.Thread(
            target=self._run, args=(project, job, force, dry_run), daemon=True, name="texclaim-run"
        )
        t.start()
        return job

    def cancel(self, pid: str) -> bool:
        j = self.jobs.get(pid)
        if not j or j.state != "running":
            return False
        j.stop.set()
        j.emit("stage", name="cancelling")
        return True

    # ---- worker ---------------------------------------------------------------------------
    def _run(self, project: Project, job: Job, force: bool, dry_run: bool) -> None:
        from texclaim.check import CheckOptions, make_verifier, run_check
        from texclaim.config import ConfigError, load_settings, resolve_secret
        from texclaim.db.state_store import RunLockedError
        from texclaim.reporting.write import write_reports

        folder = project.path
        try:
            settings = load_settings(folder, cli=project.settings.overrides())
            verifier = None if dry_run else make_verifier(settings)
            job.emit("start", model=settings.model, dry_run=dry_run)

            def on_stage(name: str) -> None:
                job.emit("stage", name=name)

            def on_plan(queued: int, reused: int) -> None:
                job.total = queued
                job.emit("plan", queued=queued, reused=reused)

            def on_result(unit, rec) -> None:
                job.done += 1
                job.cost += rec.cost_usd or 0.0
                job.emit(
                    "unit", done=job.done, total=job.total, bib_key=unit.bib_key,
                    verdict=rec.verdict, file=unit.file_path, line=unit.line_start,
                    text=unit.text_norm[:160], cost=round(job.cost, 6),
                )  # fmt: skip

            opts = CheckOptions(
                force=force, dry_run=dry_run, on_stage=on_stage, on_result=on_result,
                on_plan=on_plan, openalex_key=resolve_secret("openalex_api_key"),
                concurrency=settings.budget.concurrency,
            )  # fmt: skip
            outcome = run_check(folder, settings, verifier, opts, stop=job.stop)
            for n in outcome.notices:
                job.emit("notice", message=n)
            if not dry_run:
                job.emit("stage", name="report")
                write_reports(folder, settings, outcome, report_language=opts.report_language)
                try:
                    job.emit("stage", name="graph")
                    from texclaim.graph.build import build_graph_for

                    build_graph_for(folder, settings, verifier)
                except Exception as e:  # noqa: BLE001 - the graph is optional
                    job.emit("notice", message=f"knowledge graph not built: {e}")
            q = outcome.queue_result
            summary = {
                "status": outcome.status, "verified": q.verified, "errors": q.errors,
                "reused": outcome.reused, "cost": round(q.cost_usd, 6),
                "units": len(outcome.units), "queued": len(outcome.queue),
            }  # fmt: skip
            job.state = "cancelled" if outcome.status == "interrupted" else "done"
            project = self.store.get(project.id)
            project.last_run = {**summary, "finished": time.time(), "dry_run": dry_run}
            self.store.save(project)
            job.emit("done", **summary)
        except (ConfigError, RunLockedError) as e:
            job.state, job.error = "failed", str(e)
            job.emit("error", message=str(e))
        except Exception as e:  # noqa: BLE001
            job.state, job.error = "failed", f"{type(e).__name__}: {e}"
            job.emit("error", message=job.error, trace=traceback.format_exc()[-2000:])
