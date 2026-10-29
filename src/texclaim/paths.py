"""Filesystem locations: per-paper state directory, global cache and config directories."""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

STATE_DIRNAME = ".texclaim"


def paper_state_dir(paper: Path) -> Path:
    return paper / STATE_DIRNAME


def paper_config_path(paper: Path) -> Path:
    return paper_state_dir(paper) / "config.toml"


def paper_db_path(paper: Path) -> Path:
    return paper_state_dir(paper) / "state.db"


def paper_lock_path(paper: Path) -> Path:
    return paper_state_dir(paper) / "run.lock"


def paper_suppressions_path(paper: Path) -> Path:
    return paper_state_dir(paper) / "suppressions.toml"


def paper_logs_dir(paper: Path) -> Path:
    return paper_state_dir(paper) / "logs"


def global_config_dir() -> Path:
    override = os.environ.get("TEXCLAIM_CONFIG_DIR")
    return Path(override) if override else platformdirs.user_config_path("texclaim")


def global_config_path() -> Path:
    return global_config_dir() / "config.toml"


def global_cache_dir(override: Path | str | None = None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("TEXCLAIM_CACHE_DIR")
    return Path(env) if env else platformdirs.user_cache_path("texclaim")
