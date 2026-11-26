"""FastAPI backend for the texclaim web app (`texclaim serve`)."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shutil
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)

import texclaim
from texclaim.web.jobs import JobManager
from texclaim.web.projects import (
    MAX_UPLOAD_BYTES,
    Project,
    ProjectError,
    ProjectStore,
    WebSettings,
    add_file,
    list_files,
    safe_relpath,
)

STATIC = Path(__file__).parent / "static"
PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY", "deepseek": "DEEPSEEK_API_KEY", "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY", "azure": "AZURE_API_KEY",
}  # fmt: skip
SUGGESTED_MODELS = [
    "demo", "anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5",
    "anthropic/claude-opus-5-5", "openai/gpt-5", "openai/gpt-5-mini", "gemini/gemini-2.5-pro",
    "ollama/qwen3",
]  # fmt: skip


def _cli_agents() -> list[str]:
    from texclaim.verifier.cli_agent import available_agents

    return available_agents()


def _suggested_models() -> list[str]:
    """demo, then logged-in agent CLIs (no API key needed), then API models."""
    return ["demo", *[f"cli:{a}" for a in _cli_agents()], *SUGGESTED_MODELS[1:]]


def create_app(store: ProjectStore | None = None) -> FastAPI:
    store = store or ProjectStore()
    jobs = JobManager(store)
    app = FastAPI(title="texclaim", version=texclaim.__version__, docs_url="/api/docs")
    app.state.store, app.state.jobs = store, jobs

    def project(pid: str) -> Project:
        try:
            return store.get(pid)
        except ProjectError as e:
            raise HTTPException(404, str(e)) from e

    def report(p: Project) -> dict | None:
        f = p.path / "texclaim_report.json"
        if not f.exists():
            return None
        return json.loads(f.read_text(encoding="utf-8"))

    # ---- health ---------------------------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict:
        from texclaim.config import load_settings, resolve_secret

        model = load_settings(None).model
        return {
            "version": texclaim.__version__,
            "default_model": model,
            "model_configured": bool(model),
            "keys": {k: bool(os.environ.get(v)) for k, v in PROVIDER_KEYS.items()},
            "openalex_key": bool(resolve_secret("openalex_api_key")),
            "asta_key": bool(resolve_secret("asta_api_key")),
            "pandoc": bool(shutil.which("pandoc")),
            "suggested_models": _suggested_models(),
            "cli_agents": _cli_agents(),
        }

    # ---- global configuration (keys never leave the server) ------------------------------------
    @app.get("/api/config")
    def get_config() -> dict:
        from texclaim import envconfig
        from texclaim.config import Settings

        d = envconfig.describe()
        defaults = Settings()
        return {
            **d,
            "cli_agents": [
                {"name": a, "installed": bool(shutil.which(a))} for a in ("claude", "pi", "agy")
            ],
            "suggested_models": _suggested_models(),
            "defaults": {
                "source_order": defaults.sources.order,
                "evidence_strategy": defaults.evidence.strategy,
                "full_text_max_tokens": defaults.evidence.full_text_max_tokens,
                "passage_budget_tokens": defaults.evidence.passage_budget_tokens,
                "concurrency": defaults.budget.concurrency,
                "openalex_max_usd": defaults.sources.openalex_max_usd_per_run,
                "arxiv_max_downloads": defaults.sources.arxiv_max_downloads_per_run,
                "pdf_dirs": defaults.pdf_dirs,
                "internal_max_claims": defaults.internal.max_claims,
                "screening": defaults.internal.screening,
            },
        }

    @app.put("/api/config")
    def put_config(body: Annotated[dict, Body()]) -> dict:
        """{"values": {"ANTHROPIC_API_KEY": "sk-...", "TEXCLAIM_MODEL": "cli:claude", "X": null}}"""
        from texclaim import envconfig

        values = body.get("values") or {}
        if not isinstance(values, dict):
            raise HTTPException(400, "values must be an object")
        try:
            envconfig.write({str(k): (None if v is None else str(v)) for k, v in values.items()})
        except envconfig.ConfigValueError as e:
            raise HTTPException(400, str(e)) from e
        return get_config()

    @app.post("/api/config/test")
    async def test_config(body: Annotated[dict, Body()]) -> dict:
        """Body: {"target": "model", "model": "cli:claude"}, {"target": "openalex"} or "asta"."""
        from texclaim import model_test
        from texclaim.config import load_settings, resolve_secret

        target = body.get("target", "model")
        if target == "openalex":
            return await model_test.test_openalex(resolve_secret("openalex_api_key"))
        if target == "asta":
            return await model_test.test_asta(resolve_secret("asta_api_key"))
        model = body.get("model") or load_settings(None).model
        if not model:
            return {"ok": False, "seconds": 0, "error": "No model chosen"}
        return await model_test.test_model(str(model))

    # ---- projects ---------------------------------------------------------------------------
    @app.get("/api/projects")
    def projects() -> list[dict]:
        out = []
        for p in store.list():
            d = p.to_json()
            r = report(p)
            d["summary"] = _summary(r) if r else None
            job = jobs.current(p.id)
            d["running"] = bool(job and job.state == "running")
            out.append(d)
        return out

    @app.post("/api/projects")
    async def create_project(
        name: Annotated[str, Form()] = "",
        files: Annotated[list[UploadFile] | None, File()] = None,
    ) -> dict:
        if not files:
            raise HTTPException(400, "upload at least one file (.zip, .tex, .md or .docx)")
        p = store.create(name or Path(files[0].filename or "paper").stem)
        try:
            stored = await _store_uploads(p.path, files)
        except ProjectError as e:
            store.delete(p.id)
            raise HTTPException(400, str(e)) from e
        problem = _manuscript_problem(p.path)
        if problem:
            store.delete(p.id)
            raise HTTPException(400, problem)
        if not name:
            p.name = _guess_name(stored) or p.name
            store.save(p)
        return {**p.to_json(), "files": stored}

    @app.post("/api/projects/local")
    def open_local(body: Annotated[dict, Body()]) -> dict:
        path = Path(str(body.get("path", ""))).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise HTTPException(
                400, "Enter the full path of an existing folder, for example /home/me/paper."
            )
        problem = _manuscript_problem(path)
        if problem:
            raise HTTPException(400, problem)
        return store.create(body.get("name") or path.name, folder=path).to_json()

    @app.get("/api/projects/{pid}")
    def get_project(pid: str) -> dict:
        p = project(pid)
        r = report(p)
        job = jobs.current(pid)
        return {
            **p.to_json(),
            "summary": _summary(r) if r else None,
            "job": job.snapshot() if job else None,
            "has_graph": (p.path / ".texclaim" / "graph.json").exists(),
        }

    @app.patch("/api/projects/{pid}")
    def rename(pid: str, body: Annotated[dict, Body()]) -> dict:
        p = project(pid)
        if body.get("name"):
            p.name = str(body["name"])[:200]
        store.save(p)
        return p.to_json()

    @app.delete("/api/projects/{pid}")
    def delete_project(pid: str) -> dict:
        project(pid)
        jobs.cancel(pid)
        store.delete(pid)
        return {"ok": True}

    # ---- files ---------------------------------------------------------------------------------
    @app.get("/api/projects/{pid}/files")
    def files(pid: str) -> list[dict]:
        return list_files(project(pid).path)

    @app.post("/api/projects/{pid}/files")
    async def upload_files(pid: str, files: Annotated[list[UploadFile], File()]) -> dict:
        p = project(pid)
        try:
            return {"files": await _store_uploads(p.path, files)}
        except ProjectError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/projects/{pid}/files/raw")
    def raw_file(pid: str, path: str) -> Response:
        p = project(pid)
        try:
            f = p.path / safe_relpath(path)
        except ProjectError as e:
            raise HTTPException(400, str(e)) from e
        if not f.is_file():
            raise HTTPException(404, "file not found")
        media = "application/pdf" if f.suffix.lower() == ".pdf" else None
        return FileResponse(f, media_type=media, filename=f.name, content_disposition_type="inline")

    # ---- settings and outline --------------------------------------------------------------
    @app.get("/api/projects/{pid}/settings")
    def get_settings(pid: str) -> dict:
        return asdict(project(pid).settings)

    @app.put("/api/projects/{pid}/settings")
    def put_settings(pid: str, body: Annotated[dict, Body()]) -> dict:
        p = project(pid)
        current = asdict(p.settings)
        current.update({k: v for k, v in body.items() if k in current})
        try:
            ws = WebSettings(**current)
            if not isinstance(ws.max_usd, int | float) or not 0 <= ws.max_usd <= 1000:
                raise ValueError("the maximum cost must be between 0 and 1000 USD")
            from texclaim.config import Settings

            Settings.model_validate(_nest(ws.overrides()))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"invalid settings: {e}") from e
        if ws.model == "":
            ws.model = None
        p.settings = ws
        store.save(p)
        return asdict(ws)

    @app.get("/api/projects/{pid}/outline")
    def outline(pid: str) -> dict:
        p = project(pid)
        try:
            return _outline(p)
        except Exception as e:  # noqa: BLE001 - config errors, pandoc missing, parse failures
            raise HTTPException(400, str(e)) from e

    # ---- runs ---------------------------------------------------------------------------------
    @app.post("/api/projects/{pid}/runs")
    def start_run(pid: str, body: Annotated[dict | None, Body()] = None) -> dict:
        p = project(pid)
        body = body or {}
        try:
            job = jobs.start(p, force=bool(body.get("force")), dry_run=bool(body.get("dry_run")))
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from e
        return job.snapshot()

    @app.get("/api/projects/{pid}/runs/current")
    def current_run(pid: str) -> dict:
        project(pid)
        job = jobs.current(pid)
        if job is None:
            return {"state": "idle"}
        return {**job.snapshot(), "log": job.events[-200:]}

    @app.post("/api/projects/{pid}/runs/cancel")
    def cancel_run(pid: str) -> dict:
        project(pid)
        return {"cancelled": jobs.cancel(pid)}

    @app.get("/api/projects/{pid}/events")
    async def events(pid: str, after: int = -1) -> StreamingResponse:
        project(pid)

        async def stream():
            seq = after
            idle = 0
            while True:
                job = jobs.current(pid)
                if job is None:
                    yield "event: idle\ndata: {}\n\n"
                    return
                new = [e for e in job.events[seq + 1 :]]
                for e in new:
                    seq = e["seq"]
                    yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
                if job.state != "running" and not new:
                    yield f"event: end\ndata: {json.dumps(job.snapshot())}\n\n"
                    return
                idle = 0 if new else idle + 1
                if idle and idle % 50 == 0:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )  # fmt: skip

    # ---- results ---------------------------------------------------------------------------------
    @app.get("/api/projects/{pid}/report")
    def get_report(pid: str) -> dict:
        r = report(project(pid))
        if r is None:
            raise HTTPException(404, "no report yet; run a check first")
        return r

    @app.get("/api/projects/{pid}/report.{fmt}")
    def download_report(pid: str, fmt: str) -> Response:
        from texclaim.reporting.write import REPORT_JSON, REPORT_MD, convert_report

        p = project(pid)
        md = p.path / REPORT_MD
        if not md.exists():
            raise HTTPException(404, "no report yet; run a check first")
        name = f"{_slug(p.name)}_texclaim_report.{fmt}"
        if fmt == "md":
            from texclaim.reporting.write import strip_local_links

            return Response(
                strip_local_links(md.read_text(encoding="utf-8")),
                media_type="text/markdown",
                headers={"Content-Disposition": f'attachment; filename="{name}"'},
            )
        if fmt == "json":
            return FileResponse(p.path / REPORT_JSON, media_type="application/json", filename=name)
        if fmt in ("html", "docx"):
            try:
                out = convert_report(md, fmt)
            except Exception as e:  # noqa: BLE001
                raise HTTPException(500, f"conversion failed: {e}") from e
            media = (
                "text/html"
                if fmt == "html"
                else ("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            )
            return FileResponse(out, media_type=media, filename=name)
        raise HTTPException(400, "format must be md, json, html or docx")

    @app.get("/api/projects/{pid}/document")
    def document(pid: str) -> dict:
        p = project(pid)
        try:
            return _document(p)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, str(e)) from e

    @app.get("/api/projects/{pid}/graph")
    def graph(pid: str, rebuild: bool = False) -> dict:
        from texclaim.graph.build import build_graph_for, load_graph

        p = project(pid)
        g = None if rebuild else load_graph(p.path)
        if g is None:
            if not (p.path / ".texclaim" / "state.db").exists():
                raise HTTPException(404, "no results yet; run a check first")
            g = build_graph_for(p.path, title=p.name)
        return g

    # ---- sources -----------------------------------------------------------------------------
    @app.get("/api/projects/{pid}/sources")
    def sources(pid: str) -> list[dict]:
        p = project(pid)
        r = report(p)
        if r is None:
            return []
        counts: dict[str, dict[str, int]] = {}
        for u in r["units"]:
            c = counts.setdefault(u["bib_key"], {})
            c[u["verdict"]] = c.get(u["verdict"], 0) + 1
        out = []
        with _state(p) as (conn, cache):
            from texclaim.sources.files import source_file

            for s in r["sources"]:
                if s["bib_key"] == "@self":
                    continue
                try:
                    info = source_file(conn, cache, s["bib_key"])
                    kind, landing, doi = info.kind, info.landing_page, info.doi_url
                except KeyError:
                    kind, landing, doi = "none", None, None
                row = conn.execute(
                    "SELECT title, year, authors_json FROM references_catalog WHERE bib_key=?",
                    (s["bib_key"],),
                ).fetchone()
                authors = json.loads(row["authors_json"] or "[]") if row else []
                out.append({
                    **s, "file_kind": kind, "landing_page": landing, "doi_url": doi,
                    "title": row["title"] if row else None, "year": row["year"] if row else None,
                    "authors": [a.get("last") or a.get("first") for a in authors][:6],
                    "verdicts": counts.get(s["bib_key"], {}),
                })  # fmt: skip
        return out

    @app.get("/api/projects/{pid}/sources/{key}/file")
    def source_download(pid: str, key: str, download: bool = Query(False)) -> Response:
        p = project(pid)
        with _state(p) as (conn, cache):
            from texclaim.sources.files import source_file

            try:
                info = source_file(conn, cache, key)
            except KeyError as e:
                raise HTTPException(404, "unknown key") from e
        disp = "attachment" if download else "inline"
        if info.kind == "pdf" and info.path:
            return FileResponse(
                info.path, media_type="application/pdf", filename=info.filename,
                content_disposition_type=disp,
            )  # fmt: skip
        if info.text is not None:
            return PlainTextResponse(
                info.text,
                headers={"Content-Disposition": f'{disp}; filename="{info.filename}"'},
            )
        raise HTTPException(404, "no file for this work; upload its PDF")

    @app.post("/api/projects/{pid}/sources/{key}/pdf")
    async def source_upload(pid: str, key: str, file: Annotated[UploadFile, File()]) -> dict:
        from texclaim.sources.files import safe_name

        p = project(pid)
        data = await file.read()
        if not data.startswith(b"%PDF-"):
            raise HTTPException(400, "the file is not a PDF")
        try:
            import io as _io

            from pypdf import PdfReader

            reader = PdfReader(_io.BytesIO(data))
            text = "".join((p.extract_text() or "") for p in reader.pages[:5])
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, "the PDF could not be read; it may be damaged") from e
        if len(text.strip()) < 200:
            raise HTTPException(
                400, "the PDF has no extractable text (scanned?); texclaim cannot read it"
            )
        from texclaim.config import load_settings

        d = p.path / (load_settings(p.path).pdf_dirs or ["papers"])[0]
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"{safe_name(key)}.pdf"
        dest.write_bytes(data)
        return {"saved": dest.relative_to(p.path).as_posix(), "hint": "run the check again"}

    @app.get("/api/projects/{pid}/sources.zip")
    def sources_zip(pid: str) -> Response:
        p = project(pid)
        buf = io.BytesIO()
        with _state(p) as (conn, cache):
            from texclaim.sources.files import source_file

            keys = [r[0] for r in conn.execute("SELECT bib_key FROM references_catalog")]
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for k in keys:
                    if k == "@self":
                        continue
                    info = source_file(conn, cache, k)
                    if info.kind == "pdf" and info.path:
                        zf.write(info.path, info.filename)
                    elif info.text is not None and info.filename:
                        zf.writestr(info.filename, info.text)
        return Response(
            buf.getvalue(), media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{_slug(p.name)}_sources.zip"'},
        )  # fmt: skip

    # ---- SPA -----------------------------------------------------------------------------
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(404, "not found")
        f = (STATIC / path).resolve()
        if path and f.is_file() and STATIC.resolve() in f.parents:
            return FileResponse(f)
        index = STATIC / "index.html"
        if index.exists():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(
            "<h1>texclaim</h1><p>The web UI is not built. Run <code>make web</code>.</p>"
        )

    @app.exception_handler(ProjectError)
    async def project_error(_req, exc: ProjectError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    return app


# ---- helpers ---------------------------------------------------------------------------------
async def _store_uploads(folder: Path, files: list[UploadFile]) -> list[str]:
    stored: list[str] = []
    total = 0
    for f in files:
        data = await f.read()
        total += len(data)
        if total > MAX_UPLOAD_BYTES:
            raise ProjectError("upload too large (200 MB max)")
        stored += add_file(folder, f.filename or "upload", data)
    return stored


NO_MANUSCRIPT = (
    "No manuscript found. Upload a LaTeX file with \\documentclass (plus its .bib), "
    "a Markdown (.md) file or a Word (.docx) file."
)


def _manuscript_problem(folder: Path) -> str | None:
    from texclaim import formats
    from texclaim.config import ConfigError
    from texclaim.parser.root_finder import find_root

    try:
        kind, doc = formats.detect(folder, None)
        if kind == "latex":
            find_root(folder, None)
        elif doc is None:
            return NO_MANUSCRIPT
        else:
            formats.prepare(folder, None)  # converts with pandoc: catches damaged files
    except ConfigError as e:
        msg = str(e)
        if "pandoc failed" in msg:
            return (
                "The manuscript file could not be read; it may be damaged. "
                "Open and save it again in Word (or check the Markdown) and upload it again."
            )
        if "no root .tex" in msg:
            return NO_MANUSCRIPT
        if "several candidate" in msg:
            return (
                "Several possible main files: "
                + msg.split(":", 1)[-1].strip()
                + ". Upload one manuscript per project, or set the main file in Settings."
            )
        return msg
    return None


def _guess_name(stored: list[str]) -> str | None:
    for ext in (".tex", ".md", ".docx"):
        for s in stored:
            if s.lower().endswith(ext) and "/" not in s:
                return Path(s).stem
    return None


def _slug(name: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")[:60] or "paper"


def _nest(flat: dict) -> dict:
    out: dict = {}
    for k, v in flat.items():
        if v is None:
            continue
        cur = out
        *parents, leaf = k.split(".")
        for x in parents:
            cur = cur.setdefault(x, {})
        cur[leaf] = v
    return out


def _summary(r: dict) -> dict:
    from collections import Counter

    verdicts = Counter(u["verdict"] for u in r["units"])
    internal = Counter(u["verdict"] for u in r["units"] if u.get("claim_origin") == "internal")
    run = r["run"]
    return {
        "verdicts": dict(verdicts),
        "internal": dict(internal),
        "findings": sum(
            1 for f in r["findings"] if f.get("kind") == "unit" and not f.get("suppressed")
        ),
        "finding_verdicts": dict(
            Counter(
                f["verdict"]
                for f in r["findings"]
                if f.get("kind") == "unit" and not f.get("suppressed")
            )
        ),
        "units": len(r["units"]),
        "claims": run["counts"]["claims"],
        "cost": run["llm_cost_usd"],
        "models": run["models"],
        "finished": run["finished_at"],
        "sources": run["source_coverage"],
    }


class _state:
    def __init__(self, p: Project) -> None:
        self.p = p

    def __enter__(self):
        from texclaim import paths
        from texclaim.db.state_store import open_db
        from texclaim.sources.global_cache import GlobalCache

        if not paths.paper_db_path(self.p.path).exists():
            raise HTTPException(404, "no results yet; run a check first")
        self.conn = open_db(self.p.path)
        self.cache = GlobalCache(paths.global_cache_dir())
        return self.conn, self.cache

    def __exit__(self, *exc) -> None:
        self.cache.close()
        self.conn.close()


def _outline(p: Project) -> dict:
    from collections import Counter

    from texclaim import formats
    from texclaim.parser import parse_manuscript

    fmt = formats.prepare(p.path, p.settings.main)
    parsed = parse_manuscript(p.path, fmt.main, internal=True)
    formats.remap(fmt, parsed)
    sections: dict[str, dict] = {}
    roles = Counter()
    for c in parsed.claims:
        top = (c.section_path or "").split(" > ")[0] or ("Abstract" if c.role == "abstract" else "")
        if not top:
            top = "Front matter"
        s = sections.setdefault(top, {"title": top, "cited": 0, "internal": 0, "role": c.role})
        s["cited" if c.origin == "cited" else "internal"] += 1
        if c.role:
            roles[c.role] += 1
    keys = sorted({k.bib_key for c in parsed.claims for k in c.citations if k.bib_key != "@self"})
    return {
        "kind": fmt.kind,
        "main": fmt.original or parsed.root,
        "unit_label": fmt.unit_label,
        "sections": list(sections.values()),
        "roles": dict(roles),
        "cited_claims": sum(1 for c in parsed.claims if c.origin == "cited"),
        "internal_candidates": sum(1 for c in parsed.claims if c.origin == "internal"),
        "keys": keys,
        "diagnostics": [
            {"code": d.code, "detail": d.detail, "file": d.file, "line": d.line}
            for d in parsed.diagnostics[:50]
        ],
    }


def _document(p: Project) -> dict:
    """Manuscript text for the document view: one entry per file, with lines or paragraphs."""
    from texclaim import formats
    from texclaim.parser.root_finder import find_root

    kind, doc = formats.detect(p.path, p.settings.main)
    files = []
    if kind == "docx" and doc is not None:
        md = formats.docx_to_markdown(doc)
        files.append({
            "path": doc.relative_to(p.path).as_posix(), "unit": "paragraph",
            "lines": [re.sub(r"^#{1,6}\s+", "", p) for p in formats._paragraphs(md)],
        })  # fmt: skip
    elif kind == "markdown" and doc is not None:
        text = doc.read_text(encoding="utf-8-sig", errors="replace")
        files.append({
            "path": doc.relative_to(p.path).as_posix(), "unit": "line",
            "lines": text.splitlines(),
        })  # fmt: skip
    else:
        from texclaim.parser.latex_graph import build_graph

        root = find_root(p.path, p.settings.main)
        for f in build_graph(p.path, root).files:
            files.append({"path": f.path, "unit": "line", "lines": f.text.splitlines()})
    return {"kind": kind, "files": files}
