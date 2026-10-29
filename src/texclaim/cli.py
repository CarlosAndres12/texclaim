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
    _stub("init")


@app.command()
def check(folder: FolderArg = Path(".")) -> None:
    """Run the full verification pipeline and write reports."""
    _stub("check")


@app.command()
def fetch(folder: FolderArg = Path(".")) -> None:
    """Resolve and download sources; print the missing-source checklist."""
    _stub("fetch")


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
