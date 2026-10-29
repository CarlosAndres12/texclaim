"""`texclaim init`: create .texclaim/ with a config and a self-ignoring .gitignore."""

from __future__ import annotations

from pathlib import Path

from texclaim import paths

GITIGNORE = "*\n!.gitignore\n!config.toml\n!suppressions.toml\n"

CONFIG_TEMPLATE = """\
# texclaim paper config. Safe to commit: never put API keys here.
# main = "main.tex"                 # overrides root detection
# model = "<provider>/<model>"      # any LiteLLM model string
# report_language = "auto"          # auto | en | es
# fail_on = ["contradicted", "missing_bib_entry"]
# pdf_dirs = ["papers"]             # closed-access PDFs, named <bibkey>.pdf
"""


def ensure_gitignore(paper: Path) -> None:
    state = paths.paper_state_dir(paper)
    state.mkdir(parents=True, exist_ok=True)
    gi = state / ".gitignore"
    if not gi.exists():
        gi.write_text(GITIGNORE, encoding="utf-8")


def init_paper(paper: Path) -> list[Path]:
    """Create missing files; never overwrite. Returns the files created."""
    created: list[Path] = []
    state = paths.paper_state_dir(paper)
    state.mkdir(parents=True, exist_ok=True)
    gi = state / ".gitignore"
    if not gi.exists():
        gi.write_text(GITIGNORE, encoding="utf-8")
        created.append(gi)
    cfg = paths.paper_config_path(paper)
    if not cfg.exists():
        cfg.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        created.append(cfg)
    return created
