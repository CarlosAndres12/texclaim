"""Root document discovery (PLAN §6.1)."""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

from texclaim.config import ConfigError
from texclaim.parser.masking import mask_comments

SKIP_DIRS = {".git", ".texclaim", "node_modules", "build", "out"}
_DOCCLASS = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{([^}]*)\}")
_MAGIC_ROOT = re.compile(r"^\s*%\s*!TEX\s+root\s*=\s*(.+?)\s*$", re.I | re.M)
_LATEXMK = re.compile(r"@default_files\s*=\s*\(?\s*['\"]([^'\"]+)['\"]")
_INCLUDES = re.compile(r"\\(?:input|include|subfile|import|subimport)(?![A-Za-z])")
_NAMES = {"main", "paper", "manuscript", "article"}


def tex_files(paper: Path) -> list[Path]:
    found = []
    for dirpath, dirnames, filenames in os.walk(paper):
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith("_minted")
        )
        found += [Path(dirpath) / f for f in sorted(filenames) if f.endswith(".tex")]
    return found


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig", errors="replace")


def find_root(paper: Path, main: str | Path | None = None) -> Path:
    """First rule that yields a file wins; ties raise ConfigError (exit 2)."""
    paper = paper.resolve()
    if main:
        p = Path(main)
        p = p if p.is_absolute() else paper / p
        if not p.is_file():
            raise ConfigError(f"main file not found: {p}")
        return p.resolve()

    files = tex_files(paper)
    # 2. magic comments
    targets: Counter[Path] = Counter()
    for f in files:
        m = _MAGIC_ROOT.search(_read(f)[:2000])
        if m:
            t = (f.parent / m.group(1)).resolve()
            if t.is_file():
                targets[t] += 1
    if targets:
        return targets.most_common(1)[0][0]

    # 3. latexmkrc
    for name in (".latexmkrc", "latexmkrc"):
        rc = paper / name
        if rc.is_file():
            m = _LATEXMK.search(_read(rc))
            if m and (paper / m.group(1)).is_file():
                return (paper / m.group(1)).resolve()

    # 4. documentclass + begin{document}
    ranked = []
    for f in files:
        mask = mask_comments(_read(f))
        dc = _DOCCLASS.search(mask)
        if not dc or "\\begin{document}" not in mask:
            continue
        if dc.group(1).strip() in {"standalone", "subfiles"}:
            continue
        n_inc = len(_INCLUDES.findall(mask))
        depth = len(f.relative_to(paper).parts)
        rank = (n_inc > 0, f.stem.lower() in _NAMES, n_inc, -depth)
        ranked.append((rank, f))
    if not ranked:
        raise ConfigError(f"no root .tex file found in {paper}; pass --main")
    ranked.sort(key=lambda t: t[0], reverse=True)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        tied = [str(f.relative_to(paper)) for r, f in ranked if r == ranked[0][0]]
        raise ConfigError("several candidate root files, pass --main: " + ", ".join(tied))
    return ranked[0][1].resolve()
