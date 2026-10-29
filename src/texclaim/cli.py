"""Typer command-line interface."""

from __future__ import annotations

import subprocess
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


def _stub(name: str) -> None:
    typer.echo(f"texclaim {name}: not implemented yet", err=True)
    raise typer.Exit(2)


@app.command()
def init(folder: FolderArg = Path(".")) -> None:
    """Create .texclaim/ with config and .gitignore."""
    from texclaim.init_project import init_paper

    if not folder.is_dir():
        typer.echo(f"not a directory: {folder}", err=True)
        raise typer.Exit(2)
    created = init_paper(folder)
    for f in created:
        typer.echo(f"created {f}")
    if not created:
        typer.echo("already initialised")


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
    cache_dir: Annotated[Path | None, typer.Option("--cache-dir")] = None,
) -> None:
    """Run the full verification pipeline."""
    from texclaim.check import CheckOptions, make_verifier, run_check
    from texclaim.config import ConfigError, load_settings, resolve_secret
    from texclaim.db.state_store import RunLockedError

    if recheck not in (None, "flagged", "stale-model"):
        typer.echo("error: --recheck must be 'flagged' or 'stale-model'", err=True)
        raise typer.Exit(2)
    if evidence not in (None, "auto", "full", "passages"):
        typer.echo("error: --evidence must be auto, full or passages", err=True)
        raise typer.Exit(2)
    if api_key or openalex_api_key:
        typer.echo("warning: keys on the command line end up in shell history", err=True)
    try:
        settings = load_settings(
            folder,
            cli={
                "main": main_file, "model": model, "evidence.strategy": evidence,
                "budget.concurrency": concurrency, "offline": offline or None,
                "pdf_dirs": pdf_dir or None,
            },
        )  # fmt: skip
        verifier = None if dry_run else make_verifier(settings, api_key)
        opts = CheckOptions(
            force=force, recheck=recheck, resume=resume, only_files=only_file or [],
            only_keys=only_key or [], concurrency=settings.budget.concurrency, max_cost=max_cost,
            dry_run=dry_run, cache_dir=cache_dir,
            openalex_key=openalex_api_key or resolve_secret("openalex_api_key"),
        )  # fmt: skip
        outcome = run_check(folder, settings, verifier, opts, handle_signals=True)
    except (ConfigError, RunLockedError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from e
    parsed = outcome.prepared.parsed
    for d in parsed.diagnostics:
        where = f"{d.file}:{d.line} " if d.file and d.line else ""
        typer.echo(f"{d.severity}: {where}{d.code}: {d.detail}", err=True)
    for n in outcome.notices:
        typer.echo(f"notice: {n}", err=True)
    if dry_run:
        for c in parsed.claims:
            keys = ", ".join(dict.fromkeys(k.bib_key for k in c.citations))
            typer.echo(f"{c.file_path}:{c.line_start} [{c.unit_kind}] {keys}: {c.text_norm}")
        typer.echo(
            f"{len(outcome.units)} units, {len(outcome.queue)} would be verified, "
            f"{outcome.reused} reused"
        )
        return
    q = outcome.queue_result
    typer.echo(
        f"{q.verified} of {len(outcome.queue)} queued units verified "
        f"({outcome.reused} reused, {q.errors} errors, ${q.cost_usd:.4f})"
    )
    if outcome.status == "interrupted":
        typer.echo("interrupted; run the same command to continue", err=True)
    if outcome.incomplete:
        raise typer.Exit(3)


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
    except RunLockedError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from e
    except ConfigError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from e
    total = len(prep.results)
    full = sum(r.status == "FULL_TEXT" for r in prep.results.values())
    typer.echo(f"{full} of {total} cited works have full text")
    for row in missing_source_checklist(prep.bibdb, prep.results, settings.pdf_dirs[0]):
        typer.echo(f"\n{row['key']}  [{row['status']}]  {row['title'] or ''}")
        for label, k in (("DOI", "doi_url"), ("page", "landing_page")):
            if row[k]:
                typer.echo(f"  {label}: {row[k]}")
        typer.echo(f"  drop a PDF at: {row['drop_path']}")


@app.command()
def status(folder: FolderArg = Path(".")) -> None:
    """Show counts by verdict and source status."""
    _stub("status")


@app.command()
def show(folder: FolderArg = Path(".")) -> None:
    """Show one unit in full."""
    _stub("show")


@app.command()
def ignore(finding_id: str, folder: FolderArg = Path(".")) -> None:
    """Suppress a finding."""
    _stub("ignore")


@app.command()
def clean(folder: FolderArg = Path(".")) -> None:
    """Delete state.db, logs and cached text; keep config and suppressions."""
    _stub("clean")


@app.command()
def cache() -> None:
    """Inspect or shrink the global cache."""
    _stub("cache")


@app.command()
def doctor() -> None:
    """Check the install, FTS5, keys and connectivity."""
    _stub("doctor")


def repo_root() -> Path:
    return Path(texclaim.__file__).resolve().parents[2]


@app.command("self-install")
def self_install() -> None:
    """Re-run the editable pipx install from the repository."""
    root = repo_root()
    if not (root / "pyproject.toml").is_file():
        typer.echo(
            f"texclaim is not an editable install (no pyproject.toml at {root}); "
            "run `pipx install --editable <repo>` manually.",
            err=True,
        )
        raise typer.Exit(2)
    cmd = ["pipx", "install", "--editable", str(root), "--force"]
    constraints = root / "constraints.txt"
    if constraints.is_file():
        cmd.append(f"--pip-args=-c {constraints}")
    raise typer.Exit(subprocess.call(cmd))
