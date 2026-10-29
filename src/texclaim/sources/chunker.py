"""Overlapping chunks with page ranges, bibliography and prompt-injection flags (PLAN §8)."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

CHUNK_CHARS = 1200
OVERLAP = 200

_HEADING = re.compile(
    r"(?im)^(?:(?:\d+(?:\.\d+)*\.?|[A-Z]\.)\s+[A-Z][^\n]{1,70}"
    r"|abstract|introduction|related work|conclusions?|discussion|appendix[^\n]{0,40}"
    r"|references|bibliography|referencias|bibliograf[ií]a)$"
)
_REF_HEADING = re.compile(
    r"(?im)^(?:\d+\.?\s+)?(?:references|bibliography|referencias|bibliograf[ií]a)$"
)
_YEAR = re.compile(r"\b(?:19|20)\d\d[a-z]?\b")
_VENUE = re.compile(
    r"\b(?:et al\.|pp\.|proceedings|journal|arxiv|conference|trans\.|vol\.|in:)", re.I
)
_SUSPICIOUS = re.compile(
    r"ignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier) (?:instructions|prompts?)"
    r"|disregard (?:all |any )?(?:the )?(?:previous|prior|above)"
    r"|give (?:this paper )?(?:a )?(?:positive|favou?rable|high) review"
    r"|(?:recommend|rate) (?:this paper )?(?:for )?acceptance"
    r"|as an ai (?:language )?model|you are (?:now )?an? (?:helpful )?(?:ai|assistant)"
    r"|do not (?:mention|reveal) (?:any )?(?:weakness|flaw|limitation)"
    r"|system prompt",
    re.I,
)


@dataclass
class Chunk:
    chunk_id: str
    text_sha256: str
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    section_hint: str | None
    is_bibliography: bool
    is_suspicious: bool
    text: str


def is_suspicious(text: str) -> bool:
    return bool(_SUSPICIOUS.search(text))


_APPENDIX = re.compile(r"(?im)^appendi(?:x|ces)[^\n]{0,40}$")


def reference_region(full_text: str) -> tuple[int, int] | None:
    """(start, end) of the reference list: the last 'References' heading to the next appendix."""
    start = None
    for m in _REF_HEADING.finditer(full_text):
        if m.start() > len(full_text) * 0.3:
            start = m.start()
    if start is None:
        return None
    app = _APPENDIX.search(full_text, start)
    return start, app.start() if app else len(full_text)


def _in_region(region: tuple[int, int] | None, start: int, end: int) -> bool:
    """True if at least half of the chunk lies inside the reference list."""
    if region is None:
        return False
    overlap = min(end, region[1]) - max(start, region[0])
    return overlap * 2 >= end - start


def _bibliographic(text: str) -> bool:
    return len(_YEAR.findall(text)) >= 3 and len(_VENUE.findall(text)) >= 1


def chunk_text(full_text: str, page_spans: list[tuple[int, int]], text_sha256: str) -> list[Chunk]:
    """Chunks of ~CHUNK_CHARS with OVERLAP; page_spans[i] is the (start, end) of PDF page i+1."""
    starts = [s for s, _ in page_spans] or [0]
    headings = [(m.start(), m.group(0).strip()) for m in _HEADING.finditer(full_text)]
    heading_pos = [h[0] for h in headings]
    region = reference_region(full_text)
    n = len(full_text)
    out: list[Chunk] = []
    pos = 0
    while pos < n:
        end = min(n, pos + CHUNK_CHARS)
        if end < n:
            cut = full_text.rfind(" ", max(pos + 1, end - 150), end)
            end = cut if cut > pos else end
        text = full_text[pos:end]
        if text.strip():
            hi = bisect.bisect_right(heading_pos, pos) - 1
            out.append(
                Chunk(
                    chunk_id=f"{text_sha256[:12]}:{len(out)}",
                    text_sha256=text_sha256,
                    page_start=max(1, bisect.bisect_right(starts, pos)),
                    page_end=max(1, bisect.bisect_right(starts, max(pos, end - 1))),
                    char_start=pos,
                    char_end=end,
                    section_hint=headings[hi][1] if hi >= 0 else None,
                    is_bibliography=_in_region(region, pos, end) and _bibliographic(text),
                    is_suspicious=is_suspicious(text),
                    text=text,
                )
            )
        if end >= n:
            break
        nxt = max(end - OVERLAP, pos + 1)
        sp = full_text.find(" ", nxt, nxt + 60)  # start on a word boundary
        pos = sp + 1 if sp >= 0 else nxt
    return out
