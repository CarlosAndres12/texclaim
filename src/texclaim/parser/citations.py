"""Citation command tokenizer (PLAN §6.4)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from texclaim.parser.tex import is_escaped, match_group, skip_space

SINGLE = {
    "cite", "citep", "citet", "citealp", "citealt", "citeauthor", "citeyear", "citeyearpar",
    "citenum", "parencite", "textcite", "autocite", "footcite", "footcitetext", "smartcite",
    "supercite", "fullcite", "footfullcite", "citetitle", "citedate",
}  # fmt: skip
MULTI = {"cites", "parencites", "textcites", "autocites", "footcites", "smartcites", "supercites"}
IGNORED_MACROS = {"bibcite", "newcites", "defcitealias", "nocite"}

_CMD = re.compile(r"\\([A-Za-z]+)(\*?)")
_UNKNOWN = re.compile(r"^[a-z]*cite[a-z]*$")
_DEFINE = re.compile(
    r"\\(?:re|provide)?newcommand\*?\s*\{?\s*\\([A-Za-z]+)\s*\}?|\\DeclareRobustCommand\*?"
    r"\s*\{?\s*\\([A-Za-z]+)\s*\}?"
)
_WRAPPER_BODY = re.compile(r"\\([A-Za-z]+)\*?\s*(?:\[[^\]]*\]\s*)*\{#1\}")


@dataclass
class CiteOccurrence:
    command: str  # lower-case name without backslash or star
    start: int
    end: int
    keys: list[str]
    prenote: str | None  # raw LaTeX, normalised later
    postnote: str | None
    raw: str


@dataclass
class Definition:
    name: str
    start: int
    end: int
    is_wrapper: bool


@dataclass
class CiteScan:
    occurrences: list[CiteOccurrence]
    nocites: list[tuple[str, int]]  # key, offset
    diagnostics: list[tuple[str, str, int]]  # code, detail, offset


def find_definitions(mask: str) -> list[Definition]:
    out = []
    for m in _DEFINE.finditer(mask):
        name = m.group(1) or m.group(2)
        j = skip_space(mask, m.end())
        for _ in range(2):  # [nargs] [default]
            if j < len(mask) and mask[j] == "[":
                e = match_group(mask, j, "[")
                if e is None:
                    break
                j = skip_space(mask, e)
        if j < len(mask) and mask[j] == "{":
            e = match_group(mask, j, "{")
            if e is not None:
                body = mask[j + 1 : e - 1]
                wrap = any(w.group(1).lower() in SINGLE for w in _WRAPPER_BODY.finditer(body))
                out.append(Definition(name, m.start(), e, wrap))
    return out


def _split_keys(raw: str) -> list[str]:
    return [k.strip() for k in raw.split(",")]


def _optional_args(mask: str, j: int) -> tuple[list[str], int]:
    args: list[str] = []
    while len(args) < 2:
        k = skip_space(mask, j)
        if k < len(mask) and mask[k] == "[":
            e = match_group(mask, k, "[")
            if e is None:
                break
            args.append(mask[k + 1 : e - 1])
            j = e
        else:
            break
    return args, j


def _notes(args: list[str]) -> tuple[str | None, str | None]:
    if len(args) == 1:
        return None, args[0]
    if len(args) == 2:
        return args[0], args[1]
    return None, None


def find_citations(mask: str, extra: set[str] | frozenset[str] = frozenset()) -> CiteScan:
    defs = find_definitions(mask)
    in_def = [(d.start, d.end) for d in defs]
    single = SINGLE | {c for c in extra if c not in MULTI}
    scan = CiteScan([], [], [])

    def inside_def(pos: int) -> bool:
        return any(a <= pos < b for a, b in in_def)

    def add_keys(keys: list[str], pos: int) -> list[str]:
        good = []
        for k in keys:
            if k.startswith("#"):
                continue
            if not k:
                scan.diagnostics.append(("EMPTY_CITE_KEY", "empty key in citation", pos))
                continue
            good.append(k)
        return good

    for m in _CMD.finditer(mask):
        if is_escaped(mask, m.start()) or inside_def(m.start()):
            continue
        name = m.group(1).lower()
        if name == "nocite":
            j = skip_space(mask, m.end())
            if j < len(mask) and mask[j] == "{":
                e = match_group(mask, j, "{")
                if e:
                    for k in add_keys(_split_keys(mask[j + 1 : e - 1]), m.start()):
                        scan.nocites.append((k, m.start()))
            continue
        if name in single:
            args, j = _optional_args(mask, m.end())
            j = skip_space(mask, j)
            if j >= len(mask) or mask[j] != "{":
                continue
            e = match_group(mask, j, "{")
            if e is None:
                continue
            keys = add_keys(_split_keys(mask[j + 1 : e - 1]), m.start())
            pre, post = _notes(args)
            if keys:
                scan.occurrences.append(
                    CiteOccurrence(name, m.start(), e, keys, pre, post, mask[m.start() : e])
                )
        elif name in MULTI:
            j = m.end()
            for _ in range(2):  # (pre)(post) group notes, kept only in the raw text
                k = skip_space(mask, j)
                if k < len(mask) and mask[k] == "(":
                    e = match_group(mask, k, "(")
                    if e is None:
                        break
                    j = e
            first = True
            while True:
                g_start = m.start() if first else j
                args, k = _optional_args(mask, j)
                if k >= len(mask) or mask[k] != "{":
                    break
                e = match_group(mask, k, "{")
                if e is None:
                    break
                keys = add_keys(_split_keys(mask[k + 1 : e - 1]), m.start())
                pre, post = _notes(args)
                raw = mask[g_start:e] if first else "\\" + m.group(1) + mask[g_start:e]
                if keys:
                    scan.occurrences.append(CiteOccurrence(name, g_start, e, keys, pre, post, raw))
                j = e
                first = False
                if j >= len(mask) or mask[j] not in "[{":
                    break
        elif _UNKNOWN.match(name) and name not in IGNORED_MACROS and name not in extra:
            scan.diagnostics.append(
                ("UNKNOWN_CITE_MACRO", f"\\{m.group(1)} looks like a citation command", m.start())
            )
    return scan
