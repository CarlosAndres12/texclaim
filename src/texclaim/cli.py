"""Typer command-line interface (PLAN §12)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

import texclaim

app = typer.Typer(
    name="texclaim",
    help="Check that cited statements in a LaTeX manuscript are supported by their sources.",
    no_args_is_help=True,
    add_completion=False,
)
cache_app = typer.Typer(help="Inspect or shrink the global cache.", no_args_is_help=True)
app.add_typer(cache_app, name="cache")
sources_app = typer.Typer(help="Cited works' files.", no_args_is_help=True)
config_app = typer.Typer(
    help="Keys, default model and other global settings (the .env file).", no_args_is_help=True
)
app.add_typer(config_app, name="config")
app.add_typer(sources_app, name="sources")

FolderArg = Annotated[Path, typer.Argument(help="Paper folder (default: current directory).")]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(texclaim.__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """texclaim."""
    import os

    if not os.environ.get("TEXCLAIM_NO_DOTENV"):
        from texclaim import dotenv

        dotenv.load()


def _fail(msg: str, code: int = 2) -> typer.Exit:
    typer.echo(f"error: {msg}", err=True)
    return typer.Exit(code)


def _open_state(folder: Path):
    from texclaim import paths
    from texclaim.db.state_store import open_db

    if not paths.paper_db_path(folder).exists():
        raise _fail(f"no state in {folder}; run `texclaim check` first")
    return open_db(folder)


# ---- init ---------------------------------------------------------------------------------
def request_openalex_key(email: str) -> str | None:
    """POST /api-keys. The key works once the user clicks the emailed link."""
    import httpx

    r = httpx.post("https://api.openalex.org/api-keys", json={"email": email}, timeout=30)
    if r.status_code // 100 != 2:
        return None
    return r.json().get("api_key") or r.json().get("key")


def store_global_secret(name: str, value: str) -> str:
    """Keyring when available, else the global config at mode 0600. Returns where it went."""
    import tomllib

    import tomli_w

    from texclaim import paths
    from texclaim.config import KEYRING_SERVICE

    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, name, value)
        return "the OS keyring"
    except Exception:  # noqa: BLE001 - no keyring installed or no backend
        pass
    p = paths.global_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = tomllib.loads(p.read_text()) if p.exists() else {}
    data.setdefault("secrets", {})[name] = value
    p.write_text(tomli_w.dumps(data), encoding="utf-8")
    p.chmod(0o600)
    return str(p)


@app.command()
def init(
    folder: FolderArg = Path("."),
    openalex_key: Annotated[
        bool | None,
        typer.Option("--openalex-key/--no-openalex-key", help="Request a free OpenAlex key."),
    ] = None,
) -> None:
    """Create .texclaim/ with config and .gitignore, detect the root file."""
    from texclaim.config import ConfigError, resolve_secret
    from texclaim.init_project import init_paper
    from texclaim.parser.root_finder import find_root

    if not folder.is_dir():
        raise _fail(f"not a directory: {folder}")
    created = init_paper(folder)
    for f in created:
        typer.echo(f"created {f}")
    if not created:
        typer.echo("already initialised")
    try:
        typer.echo(f"root file: {find_root(folder).relative_to(folder.resolve())}")
    except ConfigError as e:
        typer.echo(f"note: {e}")
    ask = openalex_key
    if ask is None:
        ask = sys.stdin.isatty() and not resolve_secret("openalex_api_key")
        ask = ask and typer.confirm("Request a free OpenAlex API key (raises daily limits)?")
    if ask:
        email = typer.prompt("Your email (OpenAlex sends an activation link)")
        key = request_openalex_key(email)
        if key is None:
            typer.echo("could not obtain a key; texclaim works without one", err=True)
        else:
            where = store_global_secret("openalex_api_key", key)
            typer.echo(f"key stored in {where}; click the emailed link to activate it")


# ---- check --------------------------------------------------------------------------------
@app.command()
def check(
    folder: FolderArg = Path("."),
    main_file: Annotated[str | None, typer.Option("--main", help="Root .tex file.")] = None,
    model: Annotated[str | None, typer.Option("--model", help="LiteLLM model string.")] = None,
    api_key: Annotated[
        str | None, typer.Option("--api-key", help="Prefer the environment.")
    ] = None,
    openalex_api_key: Annotated[str | None, typer.Option("--openalex-api-key")] = None,
    force: Annotated[bool, typer.Option("--force", help="Re-verify every unit in scope.")] = False,
    recheck: Annotated[str | None, typer.Option("--recheck", help="flagged | stale-model")] = None,
    resume: Annotated[
        bool, typer.Option("--resume", help="Continue the last interrupted run.")
    ] = False,
    only_file: Annotated[list[str] | None, typer.Option("--only-file")] = None,
    only_key: Annotated[list[str] | None, typer.Option("--only-key")] = None,
    evidence: Annotated[
        str | None, typer.Option("--evidence", help="auto | full | passages")
    ] = None,
    concurrency: Annotated[int | None, typer.Option("--concurrency")] = None,
    max_cost: Annotated[float | None, typer.Option("--max-cost", help="LLM budget in USD.")] = None,
    offline: Annotated[bool, typer.Option("--offline", help="No network requests.")] = False,
    pdf_dir: Annotated[list[str] | None, typer.Option("--pdf-dir")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Plan only; no LLM calls.")] = False,
    fail_on: Annotated[
        str | None, typer.Option("--fail-on", help="Comma-separated finding kinds.")
    ] = None,
    report_dir: Annotated[Path | None, typer.Option("--report-dir")] = None,
    report_language: Annotated[
        str | None, typer.Option("--report-language", help="en | es")
    ] = None,
    claim_scope: Annotated[
        str | None,
        typer.Option("--claim-scope", help="auto (model decides) | sentence | two | paragraph"),
    ] = None,
    internal: Annotated[
        bool | None,
        typer.Option(
            "--internal/--no-internal", help="Also check uncited claims against the document."
        ),
    ] = None,
    internal_section: Annotated[
        list[str] | None,
        typer.Option("--internal-section", help="Limit internal checks to these sections."),
    ] = None,
    cache_dir: Annotated[Path | None, typer.Option("--cache-dir")] = None,
    list_uncited: Annotated[bool, typer.Option("--list-uncited")] = False,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Debug log in .texclaim/logs/.")
    ] = False,
) -> None:
    """Run the full verification pipeline and write reports."""
    from rich.console import Console

    from texclaim.check import CheckOptions, make_verifier, run_check
    from texclaim.config import ConfigError, load_settings, resolve_secret
    from texclaim.db.state_store import RunLockedError
    from texclaim.logs import setup_logging
    from texclaim.reporting.json_report import fail_matches
    from texclaim.reporting.write import write_reports

    for opt, allowed, name in (
        (recheck, (None, "flagged", "stale-model"), "--recheck"),
        (evidence, (None, "auto", "full", "passages"), "--evidence"),
        (report_language, (None, "en", "es"), "--report-language"),
        (claim_scope, (None, "auto", "sentence", "two", "paragraph"), "--claim-scope"),
    ):
        if opt not in allowed:
            raise _fail(f"invalid value for {name}: {opt}")
    if api_key or openalex_api_key:
        typer.echo("warning: keys on the command line end up in shell history", err=True)
    setup_logging(folder, verbose)
    console = Console(stderr=True)
    try:
        settings = load_settings(
            folder,
            cli={
                "main": main_file, "model": model, "evidence.strategy": evidence,
                "budget.concurrency": concurrency, "offline": offline or None,
                "pdf_dirs": pdf_dir or None, "report_language": report_language,
                "claim_scope": claim_scope, "internal.enabled": internal,
                "internal.sections": internal_section or None,
                "fail_on": [x.strip() for x in fail_on.split(",")] if fail_on else None,
            },
        )  # fmt: skip
        verifier = None if dry_run else make_verifier(settings, api_key)
        status_ctx = console.status("starting") if console.is_terminal else None
        if status_ctx:
            status_ctx.start()

        def on_stage(name: str) -> None:
            if status_ctx:
                status_ctx.update(name)

        opts = CheckOptions(
            force=force, recheck=recheck, resume=resume, only_files=only_file or [],
            only_keys=only_key or [], concurrency=settings.budget.concurrency, max_cost=max_cost,
            dry_run=dry_run, cache_dir=cache_dir, on_stage=on_stage,
            openalex_key=openalex_api_key or resolve_secret("openalex_api_key"),
        )  # fmt: skip
        try:
            outcome = run_check(folder, settings, verifier, opts, handle_signals=True)
        finally:
            if status_ctx:
                status_ctx.stop()
    except (ConfigError, RunLockedError) as e:
        raise _fail(str(e)) from e
    parsed = outcome.prepared.parsed
    for d in parsed.diagnostics:
        where = f"{d.file}:{d.line} " if d.file and d.line else ""
        typer.echo(f"{d.severity}: {where}{d.code}: {d.detail}", err=True)
    for n in outcome.notices:
        typer.echo(f"notice: {n}", err=True)
    if dry_run:
        _dry_run_output(outcome, settings, verifier)
        return
    q = outcome.queue_result
    typer.echo(
        f"{q.verified} of {len(outcome.queue)} queued units verified "
        f"({outcome.reused} reused, {q.errors} errors, ${q.cost_usd:.4f})"
    )
    md, js, rep = write_reports(
        folder, settings, outcome, report_dir=report_dir, cache_dir=cache_dir,
        list_uncited=list_uncited, report_language=opts.report_language,
    )  # fmt: skip
    typer.echo(f"report: {md}\nreport: {js}")
    if outcome.status == "interrupted":
        typer.echo(
            f"interrupted: {q.verified} of {len(outcome.queue)} units verified; "
            "run the same command to continue",
            err=True,
        )
    if outcome.status == "budget_exhausted":
        typer.echo("budget exhausted; raise --max-cost and run again (or --resume)", err=True)
    if outcome.incomplete:
        raise typer.Exit(3)
    hits = fail_matches(rep, settings.fail_on)
    if hits:
        typer.echo(f"{len(hits)} finding(s) match --fail-on ({', '.join(hits[:5])}...)", err=True)
        raise typer.Exit(1)


def _dry_run_output(outcome, settings, verifier) -> None:
    from texclaim.verifier.evidence import estimate_tokens

    parsed = outcome.prepared.parsed
    for c in parsed.claims:
        keys = ", ".join(dict.fromkeys(k.bib_key for k in c.citations))
        typer.echo(f"{c.file_path}:{c.line_start} [{c.unit_kind}] {keys}: {c.text_norm}")
    tokens = 0
    for u in outcome.queue:
        tokens += estimate_tokens(u.text_norm) + 600
        if u.strategy == "full":
            from texclaim.db.state_store import open_db
            from texclaim.verifier.evidence import source_chars

            conn = open_db(outcome.folder)
            try:
                tokens += estimate_tokens(source_chars(conn, u.text_sha256))
            finally:
                conn.close()
        elif u.strategy == "passages":
            tokens += settings.evidence.passage_budget_tokens
    cost = ""
    if settings.model:
        try:
            import litellm

            p, c_ = litellm.cost_per_token(
                model=settings.model,
                prompt_tokens=tokens,
                completion_tokens=400 * len(outcome.queue),
            )
            cost = f", estimated cost ${p + c_:.2f}"
        except Exception:  # noqa: BLE001 - unknown model price
            cost = ", cost unknown for this model"
    typer.echo(
        f"{len(outcome.units)} units, {len(outcome.queue)} would be verified, "
        f"{outcome.reused} reused; about {tokens} input tokens{cost}"
    )


# ---- fetch --------------------------------------------------------------------------------
@app.command()
def fetch(
    folder: FolderArg = Path("."),
    main_file: Annotated[str | None, typer.Option("--main", help="Root .tex file.")] = None,
    offline: Annotated[bool, typer.Option("--offline", help="No network requests.")] = False,
    openalex_api_key: Annotated[
        str | None, typer.Option("--openalex-api-key", help="Prefer the environment or keyring.")
    ] = None,
    cache_dir: Annotated[Path | None, typer.Option("--cache-dir")] = None,
    pdf_dir: Annotated[list[str] | None, typer.Option("--pdf-dir")] = None,
) -> None:
    """Resolve and download sources; print the missing-source checklist."""
    from texclaim.config import ConfigError, load_settings
    from texclaim.db.state_store import RunLockedError, run_lock
    from texclaim.pipeline import prepare
    from texclaim.sources.catalog import missing_source_checklist

    if openalex_api_key:
        typer.echo("warning: keys on the command line end up in shell history", err=True)
    try:
        settings = load_settings(
            folder,
            cli={"main": main_file, "offline": offline or None, "pdf_dirs": pdf_dir or None},
        )
        with run_lock(folder):
            prep = prepare(folder, settings, cache_dir=cache_dir, openalex_key=openalex_api_key)
    except (ConfigError, RunLockedError) as e:
        raise _fail(str(e)) from e
    total = len(prep.results)
    full = sum(r.status == "FULL_TEXT" for r in prep.results.values())
    typer.echo(f"{full} of {total} cited works have full text")
    for row in missing_source_checklist(prep.bibdb, prep.results, settings.pdf_dirs[0]):
        typer.echo(f"\n{row['key']}  [{row['status']}]  {row['title'] or ''}")
        for label, k in (("DOI", "doi_url"), ("page", "landing_page")):
            if row[k]:
                typer.echo(f"  {label}: {row[k]}")
        typer.echo(f"  drop a PDF at: {row['drop_path']}")


# ---- status / show ------------------------------------------------------------------------
@app.command()
def status(folder: FolderArg = Path(".")) -> None:
    """Counts by verdict and source status, read from the database."""
    conn = _open_state(folder)
    try:
        run = conn.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
        if run:
            typer.echo(f"last run {run['run_id']}: {run['status']} ({run['started_at']})")
        typer.echo("verdicts:")
        rows = conn.execute(
            "SELECT res.verdict, COUNT(*) n FROM (SELECT DISTINCT unit_key FROM citations) u"
            " JOIN current_results res ON res.unit_key = u.unit_key GROUP BY res.verdict"
            " ORDER BY n DESC"
        ).fetchall()
        for r in rows or []:
            typer.echo(f"  {r['verdict']}: {r['n']}")
        total = conn.execute("SELECT COUNT(DISTINCT unit_key) FROM citations").fetchone()[0]
        done = sum(r["n"] for r in rows)
        typer.echo(f"  (not yet verified: {total - done})")
        typer.echo("sources:")
        for r in conn.execute(
            "SELECT source_status, COUNT(*) n FROM references_catalog GROUP BY source_status"
            " ORDER BY n DESC"
        ):
            typer.echo(f"  {r['source_status']}: {r['n']}")
    finally:
        conn.close()


def _print_unit(u: dict) -> None:
    typer.echo(f"{u['id']} · {u['verdict']} · {u['file']}:{u['line']} · [{u['bib_key']}]")
    typer.echo(f"  claim: {u['claim_latex']}")
    typer.echo(f"  citation: {u['cite_command']}")
    for label, k in (
        ("reason", "reason_code"), ("scope", "evidence_scope"), ("analysis", "analysis"),
        ("what is wrong", "what_is_wrong"), ("source says", "what_source_says"),
        ("suggested fix", "suggested_fix"), ("confidence", "confidence"), ("model", "model"),
    ):  # fmt: skip
        if u[k] and u[k] != "NONE":
            typer.echo(f"  {label}: {u[k]}")
    for q in u["quotes"]:
        page = f"PDF page {q['page']}" + (
            f" (printed {q['page_label']})" if q.get("page_label") else ""
        )
        typer.echo(
            f'  quote: "{q["text"]}"\n         {page}'
            + (f" · {q['link']}" if q.get("link") else "")
        )


@app.command()
def show(
    folder: FolderArg = Path("."),
    at: Annotated[str | None, typer.Option("--at", help="FILE:LINE")] = None,
    key: Annotated[str | None, typer.Option("--key", help="Cited key.")] = None,
    finding: Annotated[
        str | None, typer.Option("--finding", help="Finding id, e.g. F-3a9c71e2.")
    ] = None,
    cache_dir: Annotated[Path | None, typer.Option("--cache-dir")] = None,
) -> None:
    """One unit in full: claim, evidence, quotes with page links."""
    from texclaim import paths
    from texclaim.config import load_settings
    from texclaim.reporting.json_report import build_report
    from texclaim.sources.global_cache import GlobalCache

    if sum(x is not None for x in (at, key, finding)) != 1:
        raise _fail("give exactly one of --at, --key, --finding")
    conn = _open_state(folder)
    cache = GlobalCache(paths.global_cache_dir(cache_dir))
    try:
        rep = build_report(conn, folder.resolve(), load_settings(folder), cache=cache)
    finally:
        cache.close()
        conn.close()
    if at:
        f, _, ln = at.rpartition(":")
        hits = [u for u in rep["units"] if u["file"] == f and u["line"] <= int(ln) <= u["line_end"]]
    elif key:
        hits = [u for u in rep["units"] if u["bib_key"] == key]
    else:
        hits = [u for u in rep["units"] if u["id"] == finding]
    if not hits:
        raise _fail("no matching unit", 1)
    for u in hits:
        _print_unit(u)


# ---- ignore / unignore --------------------------------------------------------------------
def _resolve_finding(folder: Path, finding_id: str) -> dict:
    conn = _open_state(folder)
    try:
        if finding_id.startswith("I-"):
            return {"issue": finding_id}
        row = conn.execute(
            "SELECT c.bib_key, cl.claim_hash FROM citations c JOIN claims cl"
            " ON cl.claim_pk = c.claim_pk WHERE c.unit_key LIKE ? LIMIT 1",
            (finding_id.removeprefix("F-") + "%",),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise _fail(f"unknown finding {finding_id}")
    return {"claim_hash": row["claim_hash"], "bib_key": row["bib_key"]}


@app.command()
def ignore(
    finding_id: str,
    folder: FolderArg = Path("."),
    reason: Annotated[str, typer.Option("--reason", help="Why this is not a problem.")] = "",
) -> None:
    """Suppress a finding (written to .texclaim/suppressions.toml)."""
    from texclaim.reporting import suppressions

    if not reason.strip():
        raise _fail("--reason is required")
    suppressions.add(folder, reason, **_resolve_finding(folder, finding_id))
    typer.echo(f"suppressed {finding_id}")


@app.command()
def unignore(finding_id: str, folder: FolderArg = Path(".")) -> None:
    """Reverse `ignore`."""
    from texclaim.reporting import suppressions

    if not suppressions.remove(folder, **_resolve_finding(folder, finding_id)):
        raise _fail(f"{finding_id} was not suppressed", 1)
    typer.echo(f"restored {finding_id}")


# ---- clean --------------------------------------------------------------------------------
@app.command()
def clean(folder: FolderArg = Path(".")) -> None:
    """Delete state.db, logs and the run lock; keep config and suppressions."""
    from texclaim import paths

    state = paths.paper_state_dir(folder)
    removed = []
    for name in ("state.db", "state.db-wal", "state.db-shm", "run.lock"):
        p = state / name
        if p.exists():
            p.unlink()
            removed.append(name)
    logs = paths.paper_logs_dir(folder)
    if logs.exists():
        shutil.rmtree(logs)
        removed.append("logs/")
    typer.echo("removed: " + (", ".join(removed) or "nothing"))


# ---- cache --------------------------------------------------------------------------------
def _cache(cache_dir: Path | None):
    from texclaim import paths
    from texclaim.sources.global_cache import GlobalCache

    return GlobalCache(paths.global_cache_dir(cache_dir))


@cache_app.command("info")
def cache_info(cache_dir: Annotated[Path | None, typer.Option("--cache-dir")] = None) -> None:
    """Size and contents of the global cache."""
    c = _cache(cache_dir)
    try:
        for k, v in c.info().items():
            typer.echo(f"{k}: {v}")
    finally:
        c.close()


@cache_app.command("path")
def cache_path(cache_dir: Annotated[Path | None, typer.Option("--cache-dir")] = None) -> None:
    """Where the global cache lives."""
    from texclaim import paths

    typer.echo(paths.global_cache_dir(cache_dir))


@cache_app.command("prune")
def cache_prune(
    older_than: Annotated[str | None, typer.Option("--older-than", help="e.g. 180d")] = None,
    max_size: Annotated[str | None, typer.Option("--max-size", help="e.g. 5GB")] = None,
    cache_dir: Annotated[Path | None, typer.Option("--cache-dir")] = None,
) -> None:
    """Delete the oldest cached files."""
    from texclaim.sources.global_cache import parse_age, parse_size

    if not older_than and not max_size:
        raise _fail("give --older-than and/or --max-size")
    c = _cache(cache_dir)
    try:
        n = c.prune(
            parse_age(older_than) if older_than else None,
            parse_size(max_size) if max_size else None,
        )
    finally:
        c.close()
    typer.echo(f"removed {n} file(s)")


# ---- doctor -------------------------------------------------------------------------------
@app.command()
def doctor(
    folder: FolderArg = Path("."),
    offline: Annotated[bool, typer.Option("--offline", help="Skip network checks.")] = False,
) -> None:
    """Check the install, FTS5, key presence (never printed), OpenAlex and the model."""
    import os

    from texclaim.config import load_settings, resolve_secret
    from texclaim.db.state_store import fts5_available

    bad = 0

    def line(ok: bool | None, text: str) -> None:
        nonlocal bad
        mark = {True: "ok  ", False: "FAIL", None: "info"}[ok]
        bad += ok is False
        typer.echo(f"[{mark}] {text}")

    root = Path(texclaim.__file__).resolve().parents[2]
    line((root / "pyproject.toml").is_file() or None, f"editable install at {root}")
    line(shutil.which("texclaim") is not None, "`texclaim` is on PATH")
    line(
        fts5_available(),
        "SQLite FTS5 available" if fts5_available() else "FTS5 missing: BM25 fallback",
    )
    present = [
        v for v in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY") if os.environ.get(v)
    ]
    line(bool(present) or None, "provider key in environment: " + (", ".join(present) or "none"))
    from texclaim.verifier.cli_agent import available_agents

    agents = available_agents()
    line(
        bool(agents) or None,
        "agent CLIs (no API key needed): "
        + (", ".join(f"cli:{a}" for a in agents) if agents else "none found (claude, pi, agy)"),
    )
    line(
        None,
        "OpenAlex key: " + ("set" if resolve_secret("openalex_api_key") else "not set (keyless)"),
    )
    settings = load_settings(folder if folder.is_dir() else None)
    if settings.model and settings.model.startswith("cli:"):
        agent = settings.model.split(":", 1)[1].split("/")[0]
        line(agent in agents, f"model {settings.model}: runs the logged-in '{agent}' CLI")
    elif settings.model:
        try:
            import litellm

            ok = bool(litellm.supports_response_schema(model=settings.model))
            line(
                None,
                f"model {settings.model}: " + ("structured output" if ok else "JSON-mode fallback"),
            )
        except Exception:  # noqa: BLE001
            line(None, f"model {settings.model}: capabilities unknown")
    else:
        line(None, "no model configured (set TEXCLAIM_MODEL)")
    if not offline:
        import httpx

        try:
            r = httpx.get(
                "https://api.openalex.org/works", params={"per_page": 1, "select": "id"}, timeout=15
            )
            line(r.status_code == 200, f"OpenAlex reachable (HTTP {r.status_code})")
        except httpx.HTTPError as e:
            line(False, f"OpenAlex unreachable ({type(e).__name__})")
    raise typer.Exit(1 if bad else 0)


# ---- self-install -------------------------------------------------------------------------
def repo_root() -> Path:
    return Path(texclaim.__file__).resolve().parents[2]


@app.command("self-install")
def self_install() -> None:
    """Re-run the editable pipx install from the repository."""
    root = repo_root()
    if not (root / "pyproject.toml").is_file():
        raise _fail(
            f"texclaim is not an editable install (no pyproject.toml at {root}); "
            "run `pipx install --editable <repo>` manually."
        )
    cmd = ["pipx", "install", "--editable", str(root), "--force"]
    constraints = root / "constraints.txt"
    if constraints.is_file():
        cmd.append(f"--pip-args=-c {constraints}")
    raise typer.Exit(subprocess.call(cmd))


# ---- sources export / report export ---------------------------------------------------------
@sources_app.command("export")
def sources_export(
    folder: FolderArg = Path("."),
    out: Annotated[
        Path | None, typer.Option("--out", help="Default: <paper>/sources_export")
    ] = None,
    cache_dir: Annotated[Path | None, typer.Option("--cache-dir")] = None,
) -> None:
    """Copy each cited work's PDF (or its extracted text/abstract) into a folder."""
    from texclaim import paths
    from texclaim.sources.files import export_all
    from texclaim.sources.global_cache import GlobalCache

    conn = _open_state(folder)
    cache = GlobalCache(paths.global_cache_dir(cache_dir))
    dest = out or (folder / "sources_export")
    try:
        infos = export_all(conn, cache, dest)
    finally:
        cache.close()
        conn.close()
    for i in infos:
        where = i.filename or (i.landing_page or i.doi_url or "-")
        typer.echo(f"{i.bib_key:24} {i.kind:8} {where}")
    typer.echo(f"exported to {dest}")


@app.command("export")
def export_report(
    folder: FolderArg = Path("."),
    fmt: Annotated[str, typer.Option("--format", help="html | docx")] = "html",
) -> None:
    """Convert texclaim_report.md to HTML or Word."""
    from texclaim.reporting.write import REPORT_MD, convert_report

    md = folder / REPORT_MD
    if not md.exists():
        raise _fail(f"{md} not found; run `texclaim check` first")
    if fmt not in ("html", "docx"):
        raise _fail("--format must be html or docx")
    typer.echo(str(convert_report(md, fmt)))


# ---- web app, knowledge graph, MCP -------------------------------------------------------------
@app.command()
def serve(
    host: Annotated[str | None, typer.Option("--host", help="Default 127.0.0.1")] = None,
    port: Annotated[int | None, typer.Option("--port", help="Default 8765")] = None,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = False,
) -> None:
    """Start the web app (English/Spanish UI) on this machine."""
    import os

    import uvicorn

    from texclaim.web.app import create_app

    host = host or os.environ.get("TEXCLAIM_HOST") or "127.0.0.1"
    port = port or int(os.environ.get("TEXCLAIM_PORT") or 8765)
    if host not in ("127.0.0.1", "localhost", "::1"):
        typer.echo(
            "warning: the web app has no login; anyone who can reach this address can use "
            "your API keys",
            err=True,
        )
    url = f"http://{host}:{port}"
    typer.echo(f"texclaim web app: {url}")
    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


@app.command()
def graph(
    folder: FolderArg = Path("."),
    llm: Annotated[
        bool, typer.Option("--llm/--heuristic", help="Extract entities with the model.")
    ] = False,
) -> None:
    """Build the knowledge graph (.texclaim/graph.json) from the latest results."""
    from texclaim.check import make_verifier
    from texclaim.config import ConfigError, load_settings
    from texclaim.graph.build import build_graph_for, graph_path

    _open_state(folder).close()
    verifier = None
    if llm:
        try:
            verifier = make_verifier(load_settings(folder))
        except ConfigError as e:
            raise _fail(str(e)) from e
    g = build_graph_for(folder.resolve(), verifier=verifier)
    c = g["stats"]["counts"]
    typer.echo(
        f"{len(g['nodes'])} nodes ({', '.join(f'{v} {k}' for k, v in c.items())}), "
        f"{len(g['edges'])} edges -> {graph_path(folder.resolve())}"
    )


@app.command()
def mcp(folder: FolderArg = Path(".")) -> None:
    """Serve the paper's knowledge graph to agents over MCP (stdio)."""
    from texclaim.graph.mcp_server import serve_stdio

    serve_stdio(folder)


# ---- config ---------------------------------------------------------------------------------
@config_app.command("show")
def config_show(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Show which keys are set (never their values) and the global defaults."""
    import json

    from texclaim import envconfig
    from texclaim.verifier.cli_agent import available_agents

    d = envconfig.describe()
    d["cli_agents"] = available_agents()
    if as_json:
        typer.echo(json.dumps(d, indent=2))
        return
    typer.echo(f"file: {d['file']}")
    typer.echo("keys:")
    for k, v in d["secrets"].items():
        src = " (from environment)" if v["from_environment"] else ""
        typer.echo(f"  {k:22} {'set' if v['set'] else '-'}{src}   {v['label']}")
    typer.echo("settings:")
    for k, v in d["settings"].items():
        typer.echo(f"  {k:26} {v['value'] or '-'}")
    agents = ", ".join(f"cli:{a}" for a in d["cli_agents"]) or "none"
    typer.echo(f"agent CLIs (no API key needed): {agents}")


@config_app.command("set")
def config_set(
    assignments: Annotated[list[str], typer.Argument(help="NAME=VALUE pairs")],
) -> None:
    """Set keys or defaults, e.g. `texclaim config set TEXCLAIM_MODEL=cli:claude`.

    Prefer `texclaim config set ANTHROPIC_API_KEY` (no value): it asks without echoing."""
    from texclaim import envconfig

    updates: dict[str, str | None] = {}
    for a in assignments:
        name, sep, value = a.partition("=")
        name = name.strip().upper()
        if not sep:
            if name not in envconfig.SECRETS:
                raise _fail(f"use NAME=VALUE for {name}")
            value = typer.prompt(name, hide_input=True)
        updates[name] = value
    try:
        path = envconfig.write(updates)
    except envconfig.ConfigValueError as e:
        raise _fail(str(e)) from e
    typer.echo(f"saved {', '.join(updates)} to {path}")


@config_app.command("unset")
def config_unset(names: Annotated[list[str], typer.Argument()]) -> None:
    """Remove keys or defaults from the .env file."""
    from texclaim import envconfig

    try:
        path = envconfig.write({n.upper(): None for n in names})
    except envconfig.ConfigValueError as e:
        raise _fail(str(e)) from e
    typer.echo(f"removed {', '.join(n.upper() for n in names)} from {path}")


@config_app.command("test")
def config_test(
    model: Annotated[
        str | None, typer.Option("--model", help="Default: the configured model")
    ] = None,
    openalex: Annotated[bool, typer.Option("--openalex")] = False,
    asta: Annotated[bool, typer.Option("--asta")] = False,
) -> None:
    """Send a tiny request to the model (or OpenAlex/Asta) and report whether it works."""
    import asyncio

    from texclaim import model_test
    from texclaim.config import load_settings, resolve_secret

    checks = []
    if openalex:
        checks.append(("OpenAlex", model_test.test_openalex(resolve_secret("openalex_api_key"))))
    if asta:
        checks.append(("Asta", model_test.test_asta(resolve_secret("asta_api_key"))))
    if model or not checks:
        m = model or load_settings(None).model
        if not m:
            raise _fail("no model configured; pass --model or set TEXCLAIM_MODEL")
        checks.append((m, model_test.test_model(m)))
    failed = False
    for name, coro in checks:
        r = asyncio.run(coro)
        failed |= not r["ok"]
        detail = r.get("reply") if r["ok"] else r.get("error")
        typer.echo(f"[{'ok  ' if r['ok'] else 'FAIL'}] {name} ({r['seconds']} s): {detail}")
    if failed:
        raise typer.Exit(1)


@config_app.command("path")
def config_path() -> None:
    """Print the .env file texclaim reads and writes."""
    from texclaim import envconfig

    typer.echo(str(envconfig.env_file()))
