"""Small TeX scanning helpers shared by the parser modules."""

from __future__ import annotations

import bisect
import re

_CLOSE = {"{": "}", "[": "]", "(": ")"}


def match_group(text: str, i: int, open_ch: str = "{") -> int | None:
    """Index just past the group opened at text[i]; braces nest inside [..] and (..) groups."""
    close = _CLOSE[open_ch]
    n = len(text)
    depth = 0
    j = i
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{" and open_ch != "{":
            end = match_group(text, j, "{")
            if end is None:
                return None
            j = end
            continue
        if c == open_ch:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return None


def skip_space(text: str, i: int) -> int:
    """Skip whitespace after a command, but never across a blank line."""
    j = i
    newlines = 0
    while j < len(text) and text[j] in " \t\r\n":
        if text[j] == "\n":
            newlines += 1
            if newlines > 1:
                return i
        j += 1
    return j


def is_escaped(text: str, i: int) -> bool:
    """True if the character at i is preceded by an odd number of backslashes."""
    n = 0
    j = i - 1
    while j >= 0 and text[j] == "\\":
        n += 1
        j -= 1
    return n % 2 == 1


class LineIndex:
    """Offset -> 1-based line number."""

    def __init__(self, text: str) -> None:
        self._starts = [0] + [m.end() for m in re.finditer(r"\n", text)]

    def line(self, offset: int) -> int:
        return bisect.bisect_right(self._starts, offset)


_SECTION = re.compile(
    r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)"
    r"(?![A-Za-z])\*?"
)
LEVELS = {
    "part": 0,
    "chapter": 1,
    "section": 2,
    "subsection": 3,
    "subsubsection": 4,
    "paragraph": 5,
    "subparagraph": 6,
}


def find_sections(mask: str) -> list[tuple[int, int, int, str]]:
    """(start, end, level, raw title) for each sectioning command."""
    out = []
    for m in _SECTION.finditer(mask):
        if is_escaped(mask, m.start()):
            continue
        j = skip_space(mask, m.end())
        if j < len(mask) and mask[j] == "[":
            e = match_group(mask, j, "[")
            if e is None:
                continue
            j = skip_space(mask, e)
        if j < len(mask) and mask[j] == "{":
            e = match_group(mask, j, "{")
            if e is not None:
                out.append((m.start(), e, LEVELS[m.group(1)], mask[j + 1 : e - 1]))
    return out
