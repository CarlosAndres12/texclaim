"""Minimal `.env` loader: KEY=VALUE lines, never overrides variables already set."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key and value:
            out[key] = value
    return out


def candidates() -> list[Path]:
    env = os.environ.get("TEXCLAIM_ENV_FILE")
    paths = [Path(env)] if env else []
    paths += [Path.cwd() / ".env", REPO_ROOT / ".env"]
    from texclaim.paths import global_config_dir

    paths.append(global_config_dir() / ".env")  # written by `texclaim config` on regular installs
    seen: list[Path] = []
    for p in paths:
        r = p.resolve()
        if r not in seen:
            seen.append(r)
    return seen


def load(paths: list[Path] | None = None, environ: dict | None = None) -> list[Path]:
    """Load every existing file; earlier files win, real environment variables always win."""
    environ = os.environ if environ is None else environ
    loaded: list[Path] = []
    for p in candidates() if paths is None else paths:
        try:
            values = parse(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        loaded.append(p)
        for k, v in values.items():
            environ.setdefault(k, v)
    return loaded
