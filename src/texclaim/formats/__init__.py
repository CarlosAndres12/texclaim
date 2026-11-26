"""Input formats: LaTeX (native), Markdown and Word (converted to a shadow LaTeX tree).

Markdown and Word manuscripts are converted with pandoc into `.texclaim/shadow/main.tex` (plus a
generated .bib when needed) and parsed by the LaTeX parser unchanged. Claim locations are then
mapped back to the original file: a line number for Markdown, a paragraph number for Word.
"""

from __future__ import annotations

import bisect
import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from texclaim import paths
from texclaim.config import ConfigError
from texclaim.formats.refs import convert_reference_list, fold
from texclaim.models import SourceFile

MD_EXT = {".md", ".markdown", ".mdown", ".mkd"}
DOCX_EXT = {".docx"}
SKIP_NAMES = {"readme", "changelog", "license", "contributing", "notes", "todo"}
PREFERRED = {"main", "paper", "manuscript", "article", "draft", "articulo", "artículo"}
SHADOW = "shadow"

TEMPLATE = r"""\documentclass{article}
\begin{document}
$if(abstract)$
\section*{Abstract}
$abstract$

$endif$
$body$
%%TEXCLAIM-BIB: $for(bibliography)$$bibliography$;$endfor$
\end{document}
"""


@dataclass
class Located:
    """Original-document positions: one entry per line (Markdown) or paragraph (Word)."""

    starts: list[int] = field(default_factory=list)  # offsets into `flat`
    flat: str = ""

    @classmethod
    def build(cls, units: list[str]) -> Located:
        loc = cls()
        parts = []
        pos = 0
        for u in units:
            n = norm(u)
            loc.starts.append(pos)
            parts.append(n)
            pos += len(n)
        loc.flat = "".join(parts)
        return loc

    def find(self, text: str, from_end: bool = False) -> int | None:
        """1-based unit number containing `text` (its start, or its end if from_end)."""
        n = norm(text)
        if not n:
            return None
        for size in (80, 50, 30, 18):
            if len(n) < size and size != 18:
                continue
            probe = n[-size:] if from_end else n[:size]
            i = self.flat.find(probe)
            if i >= 0:
                if from_end:
                    i += len(probe) - 1
                return bisect.bisect_right(self.starts, i)
        return None


_CITE_TOKENS = re.compile(r"\[[^\]]*@[^\]]*\]|@[\w:.\-]+|\[\d+(?:[-\u2013,\s]+\d+)*\]")


def norm(s: str) -> str:
    s = _CITE_TOKENS.sub(" ", s)
    return re.sub(r"[^a-z0-9]", "", fold(s))


@dataclass
class Prepared:
    kind: str  # latex | markdown | docx
    original: str | None = None  # path of the original document, relative to the paper folder
    main: str | None = None  # LaTeX root to parse, relative to the paper folder
    located: Located | None = None
    shadow_lines: list[str] = field(default_factory=list)
    original_file: SourceFile | None = None
    unit_label: str = "line"  # line | paragraph


def _candidates(paper: Path, exts: set[str]) -> list[Path]:
    from texclaim.parser.root_finder import SKIP_DIRS

    found = []
    for dirpath, dirnames, filenames in os.walk(paper):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for f in sorted(filenames):
            p = Path(dirpath) / f
            if p.suffix.lower() in exts and not f.startswith(("~$", ".")):
                if p.stem.lower() not in SKIP_NAMES:
                    found.append(p)
    return found


def _pick(paper: Path, files: list[Path], what: str) -> Path | None:
    if not files:
        return None
    if len(files) == 1:
        return files[0]
    top = [f for f in files if f.parent == paper] or files
    pref = [f for f in top if f.stem.lower() in PREFERRED]
    if len(pref) == 1:
        return pref[0]
    if len(top) == 1:
        return top[0]
    names = ", ".join(str(f.relative_to(paper)) for f in top)
    raise ConfigError(f"several candidate {what} files, pass --main: {names}")


def detect(paper: Path, main: str | None) -> tuple[str, Path | None]:
    paper = paper.resolve()
    if main:
        p = Path(main)
        p = p if p.is_absolute() else paper / p
        ext = p.suffix.lower()
        if ext in MD_EXT:
            return "markdown", p
        if ext in DOCX_EXT:
            return "docx", p
        return "latex", None
    from texclaim.parser.root_finder import tex_files

    if tex_files(paper):
        return "latex", None
    if md := _pick(paper, _candidates(paper, MD_EXT), "Markdown"):
        return "markdown", md
    if dx := _pick(paper, _candidates(paper, DOCX_EXT), "Word"):
        return "docx", dx
    return "latex", None  # find_root reports "no root .tex file"


def pandoc_bin() -> str:
    exe = shutil.which("pandoc")
    if not exe:
        raise ConfigError(
            "pandoc is required for Markdown and Word manuscripts; install it from pandoc.org"
        )
    return exe


def _run(args: list[str], stdin: str | None = None, cwd: Path | None = None) -> str:
    try:
        r = subprocess.run(
            [pandoc_bin(), *args],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=cwd,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise ConfigError("pandoc timed out") from e
    if r.returncode != 0:
        raise ConfigError(f"pandoc failed: {r.stderr.strip()[:500]}")
    return r.stdout


_FRONT = re.compile(r"\A---\s*\n.*?\n(?:---|\.\.\.)\s*\n", re.S)


def docx_to_markdown(path: Path) -> str:
    md = _run([str(path), "-f", "docx+citations", "-t", "markdown", "-s", "--wrap=none",
               "--track-changes=accept"])  # fmt: skip
    # Literal citations typed in Word come back escaped: \[@key\], \@key
    return re.sub(r"\\([\[\]@])", r"\1", md)


def _paragraphs(md: str) -> list[str]:
    """Paragraph blocks of a Markdown text (front matter dropped), one entry per block."""
    md = _FRONT.sub("", md)
    return [b for b in re.split(r"\n[ \t]*\n", md) if b.strip()]


def prepare(paper: Path, main: str | None) -> Prepared:
    paper = paper.resolve()
    kind, doc = detect(paper, main)
    if kind == "latex" or doc is None:
        return Prepared("latex", main=main)
    if not doc.is_file():
        raise ConfigError(f"main file not found: {doc}")
    shadow = paths.paper_state_dir(paper) / SHADOW
    shadow.mkdir(parents=True, exist_ok=True)
    raw = doc.read_bytes()
    rel = os.path.relpath(doc, paper)
    if kind == "docx":
        md = docx_to_markdown(doc)
        label = "paragraph"
    else:
        md = raw.decode("utf-8-sig", errors="replace")
        label = "line"

    bib_paths: list[str] = []
    converted = convert_reference_list(md)
    if converted is not None:
        md, bibtex = converted  # line count is preserved
        (shadow / "references-list.bib").write_text(bibtex, encoding="utf-8")
        bib_paths.append("references-list.bib")
    units = _paragraphs(md) if kind == "docx" else md.splitlines()

    template = shadow / "template.latex"
    template.write_text(TEMPLATE, encoding="utf-8")
    latex = _run(["-f", "markdown", "-t", "latex", "--biblatex", "--wrap=preserve",
                  "--template", str(template)], stdin=md, cwd=doc.parent)  # fmt: skip
    embedded = _run(["-f", "markdown", "-s", "-t", "bibtex"], stdin=md, cwd=doc.parent)
    if embedded.strip():
        (shadow / "embedded.bib").write_text(embedded, encoding="utf-8")
        bib_paths.append("embedded.bib")

    m = re.search(r"%%TEXCLAIM-BIB: (.*)", latex)
    declared = [b for b in (m.group(1).split(";") if m else []) if b.strip()]
    for b in declared:
        p = (doc.parent / b.strip()).resolve()
        if p.is_file():
            bib_paths.append(os.path.relpath(p, shadow))
    if not declared and converted is None and not embedded.strip():
        for p in sorted(paper.glob("*.bib")) + sorted(doc.parent.glob("*.bib")):
            r = os.path.relpath(p.resolve(), shadow)
            if r not in bib_paths:
                bib_paths.append(r)
    bib_lines = "".join(f"\\addbibresource{{{b}}}\n" for b in bib_paths)
    latex = re.sub(r"%%TEXCLAIM-BIB: .*\n", lambda _m: bib_lines, latex)
    (shadow / "main.tex").write_text(latex, encoding="utf-8")

    return Prepared(
        kind=kind,
        original=rel,
        main=os.path.relpath(shadow / "main.tex", paper),
        located=Located.build(units),
        shadow_lines=latex.splitlines(),
        original_file=SourceFile(rel, kind, hashlib.sha256(raw).hexdigest(), len(raw)),
        unit_label=label,
    )


def remap(prep: Prepared, parsed) -> None:
    """Point claims and diagnostics of a converted manuscript at the original document."""
    if prep.kind == "latex" or prep.located is None:
        return
    loc = prep.located
    last = 1
    for c in sorted(parsed.claims, key=lambda c: c.char_start):
        start = loc.find(c.text_norm) or last
        end = loc.find(c.text_norm, from_end=True)
        c.file_path = prep.original
        c.line_start = start
        c.line_end = end if end and end >= start else start
        last = start
    for d in parsed.diagnostics:
        if d.file and d.file == prep.main:
            text = (
                prep.shadow_lines[d.line - 1] if d.line and d.line <= len(prep.shadow_lines) else ""
            )
            d.file = prep.original
            d.line = loc.find(_strip_latex(text)) if text else None
    if prep.original_file is not None:
        parsed.files.append(prep.original_file)


def _strip_latex(s: str) -> str:
    return re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])*|[{}]", " ", s)
