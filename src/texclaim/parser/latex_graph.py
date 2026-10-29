"""Include graph and section tracking (PLAN §6.2)."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from texclaim.models import Diagnostic, SourceFile
from texclaim.parser.masking import mask_comments
from texclaim.parser.tex import LineIndex, find_sections, match_group, skip_space

_INCLUDE = re.compile(r"\\(input|include|subfile|import|subimport|includeonly)(\*?)(?![A-Za-z])")
_BIBRES = re.compile(r"\\(bibliography|addbibresource)(?![A-Za-z])")


@dataclass
class BibResource:
    raw: str
    file: str
    line: int
    kind: str  # bibliography | addbibresource


@dataclass
class Graph:
    root_rel: str
    files: list[SourceFile] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    bib_resources: list[BibResource] = field(default_factory=list)
    includeonly: bool = False


def _groups(mask: str, i: int, count: int) -> tuple[list[str], int] | None:
    args = []
    j = i
    for _ in range(count):
        j = skip_space(mask, j)
        if j >= len(mask) or mask[j] != "{":
            return None
        e = match_group(mask, j, "{")
        if e is None:
            return None
        args.append(mask[j + 1 : e - 1].strip())
        j = e
    return args, j


def _candidates(kind: str, args: list[str], root_dir: Path, cur_dir: Path) -> list[Path]:
    if kind in ("input", "include"):
        name = args[0]
        bases = [root_dir / name] if kind == "include" else [root_dir / name, cur_dir / name]
    elif kind == "subfile":
        bases = [cur_dir / args[0], root_dir / args[0]]
    elif kind == "import":
        d = Path(args[0])
        bases = [(d if d.is_absolute() else root_dir / d) / args[1]]
    else:  # subimport
        bases = [cur_dir / args[0] / args[1]]
    out = []
    for b in bases:
        out += [b] if b.suffix == ".tex" else [b.with_name(b.name + ".tex"), b]
    return out


def build_graph(paper: Path, root: Path) -> Graph:
    paper = paper.resolve()
    root = root.resolve()
    root_dir = root.parent

    def rel(p: Path) -> str:
        return os.path.relpath(p, paper)

    g = Graph(root_rel=rel(root))
    visited: set[Path] = set()
    active: list[Path] = []

    def visit(
        path: Path,
        entry: tuple,
    ) -> tuple:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig", errors="replace")
        sf = SourceFile(
            path=rel(path),
            kind="tex",
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            text=text,
            entry_stack=entry,
        )
        g.files.append(sf)
        visited.add(path)
        active.append(path)
        mask = mask_comments(text)
        lines = LineIndex(text)

        events: list[tuple[int, str, object]] = []
        for _start, end, level, title in find_sections(mask):
            events.append((end, "section", (level, title)))
        for m in _INCLUDE.finditer(mask):
            kind = m.group(1)
            if kind == "includeonly":
                g.includeonly = True
                continue
            need = 2 if kind in ("import", "subimport") else 1
            parsed = _groups(mask, m.end(), need)
            if parsed is None and kind == "input":
                mm = re.compile(r"\s+([^\s{}\\]+)").match(mask, m.end())
                if mm:
                    parsed = ([mm.group(1)], mm.end())
            if parsed is None:
                continue
            events.append((parsed[1], "include", (kind, parsed[0], m.start())))
        for m in _BIBRES.finditer(mask):
            j = skip_space(mask, m.end())
            if m.group(1) == "addbibresource" and j < len(mask) and mask[j] == "[":
                e = match_group(mask, j, "[")
                j = skip_space(mask, e) if e else j
            parsed = _groups(mask, j, 1)
            if parsed:
                g.bib_resources.append(
                    BibResource(parsed[0][0], sf.path, lines.line(m.start()), m.group(1))
                )
        events.sort(key=lambda e: e[0])

        stack = entry
        for offset, ev, payload in events:
            if ev == "section":
                level, title = payload
                from texclaim.parser.text import latex_to_text

                stack = tuple(s for s in stack if s[0] < level) + ((level, latex_to_text(title)),)
                sf.section_events.append((offset, stack))
                continue
            kind, args, start = payload
            line = lines.line(start)
            found = next(
                (c for c in _candidates(kind, args, root_dir, path.parent) if c.is_file()), None
            )
            if found is None:
                g.diagnostics.append(
                    Diagnostic(
                        "UNRESOLVED_INCLUDE",
                        f"\\{kind}{{{'}{'.join(args)}}} not found",
                        "warning",
                        sf.path,
                        line,
                    )
                )
                continue
            found = found.resolve()
            if found in active:
                g.diagnostics.append(
                    Diagnostic(
                        "INCLUDE_CYCLE",
                        f"{rel(found)} includes itself through {sf.path}; back-edge skipped",
                        "warning",
                        sf.path,
                        line,
                    )
                )
                continue
            if found in visited:
                continue
            stack = visit(found, stack)
            sf.section_events.append((offset, stack))
        active.pop()
        return stack

    visit(root, ())
    return g


def section_path(sf: SourceFile, offset: int) -> str:
    stack = sf.entry_stack
    for off, st in sf.section_events:
        if off > offset:
            break
        stack = st
    return " > ".join(title for _, title in stack)
