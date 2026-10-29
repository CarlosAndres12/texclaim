"""Evidence assembly: what the verifier is allowed to see (PLAN §11.2)."""

from __future__ import annotations

import bisect
import math
import re
import sqlite3
from dataclasses import dataclass, field

from texclaim.db.source_store import search_chunks

CHARS_PER_TOKEN = 4

_NAMED = (
    r"(?:Table|Tab\.|Figure|Fig\.|Theorem|Thm\.|Lemma|Lem\.|Proposition|Prop\.|Definition|Def\.|"
    r"Equation|Eq\.|Section|Sec\.|§|Algorithm|Alg\.|Appendix|App\.)"
)
_LOCATOR = re.compile(_NAMED + r"\s*~?\s*([A-Z]?\d+(?:\.\d+)*[a-z]?|[A-Z])\b")
_PAGES = re.compile(r"\bpp?\.\s*~?\s*(\d+)(?:\s*[-–]\s*(\d+))?")
_ALIASES = {
    "tab": "table", "fig": "figure", "thm": "theorem", "lem": "lemma", "prop": "proposition",
    "def": "definition", "eq": "equation", "sec": "section", "alg": "algorithm", "app": "appendix",
}  # fmt: skip


def estimate_tokens(text_or_len: str | int) -> int:
    n = text_or_len if isinstance(text_or_len, int) else len(text_or_len)
    return math.ceil(n / CHARS_PER_TOKEN)


@dataclass
class Block:
    id: str
    tag: str
    text: str
    page: int
    chunk_id: str | None = None
    # (block_start, block_end, full_text_start): maps block offsets back to the stored text
    segments: list[tuple[int, int, int]] = field(default_factory=list)


@dataclass
class Evidence:
    strategy: str  # full | passages | abstract | none
    scope: str  # full_text | passages | abstract | none
    blocks: list[Block]
    page_labels: dict[int, str | None] = field(default_factory=dict)
    page_starts: list[int] = field(default_factory=list)

    def to_full_offset(self, block: Block, offset: int) -> int:
        for b0, b1, f0 in block.segments:
            if b0 <= offset <= b1:
                return f0 + (offset - b0)
        return offset

    def page_at(self, full_offset: int) -> int:
        if not self.page_starts:
            return 1
        return max(1, bisect.bisect_right(self.page_starts, full_offset))

    def locate(self, block: Block, start: int, end: int) -> dict:
        f0 = self.to_full_offset(block, start)
        f1 = self.to_full_offset(block, max(start, end - 1)) + 1
        page = self.page_at(f0) if block.chunk_id or len(block.segments) else block.page
        if not block.chunk_id:
            page = block.page
        return {
            "block_id": block.id,
            "chunk_id": block.chunk_id,
            "page": page,
            "page_label": self.page_labels.get(page),
            "char_start": f0,
            "char_end": f1,
        }


SCOPES = {"full": "full_text", "passages": "passages", "abstract": "abstract", "none": "none"}


def source_chars(conn: sqlite3.Connection, text_sha256: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(LENGTH(text)),0) + 2*MAX(COUNT(*)-1,0) FROM source_pages"
        " WHERE text_sha256=?",
        (text_sha256,),
    ).fetchone()
    return row[0]


def choose_strategy(
    status: str,
    n_tokens: int,
    setting: str,
    full_text_max_tokens: int,
) -> str:
    """Depends only on source size and the configured budget, never on the model (D6)."""
    if status == "ABSTRACT_ONLY":
        return "abstract"
    if status != "FULL_TEXT":
        return "none"
    if setting == "full":
        return "full"
    if setting == "passages":
        return "passages"
    return "full" if n_tokens <= full_text_max_tokens else "passages"


def effective_full_max(configured: int, context_window: int | None, margin: int = 4000) -> int:
    """Lower the full-text budget when the model's context window cannot hold it."""
    if context_window is None:
        return configured
    return max(1000, min(configured, context_window - margin))


def _pages(conn: sqlite3.Connection, sha: str):
    rows = conn.execute(
        "SELECT page_index, page_label, text FROM source_pages WHERE text_sha256=?"
        " ORDER BY page_index",
        (sha,),
    ).fetchall()
    starts, pos = [], 0
    for r in rows:
        starts.append(pos)
        pos += len(r["text"]) + 2
    return rows, starts


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def locator_hints(prenote: str | None, postnote: str | None) -> tuple[list[str], list[str]]:
    """(named locators like 'table 3', printed page numbers) from the citation notes."""
    text = " ".join(filter(None, [prenote, postnote]))
    names = []
    for m in _LOCATOR.finditer(text):
        word = re.match(r"[A-Za-z§]+", m.group(0))
        w = word.group(0).lower() if word else ""
        names.append(f"{_ALIASES.get(w, w)} {m.group(1).lower()}")
    pages: list[str] = []
    for m in _PAGES.finditer(text):
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        pages += [str(p) for p in range(lo, min(hi, lo + 20) + 1)]
    return names, pages


def _chunk_has_named(text: str, names: list[str]) -> bool:
    low = text.lower()
    for n in names:
        word, num = n.rsplit(" ", 1)
        stems = {word, word[:3], word[:4]}
        for s in stems:
            if re.search(rf"\b{re.escape(s)}\w*\.?\s*~?{re.escape(num)}\b", low):
                return True
    return False


def build_evidence(
    conn: sqlite3.Connection,
    *,
    strategy: str,
    text_sha256: str | None,
    query_text: str = "",
    prenote: str | None = None,
    postnote: str | None = None,
    passage_budget_tokens: int = 8000,
) -> Evidence:
    scope = SCOPES[strategy]
    if strategy == "none" or not text_sha256:
        return Evidence("none", "none", [])
    pages, starts = _pages(conn, text_sha256)
    labels = {r["page_index"]: r["page_label"] for r in pages}

    def tag_page(idx: int) -> str:
        lab = labels.get(idx)
        return f"P{idx} · p.{lab}" if lab else f"P{idx}"

    if strategy == "abstract":
        text = pages[0]["text"] if pages else ""
        b = Block("ABSTRACT", "[[ABSTRACT]]", text, 1, None, [(0, len(text), 0)])
        return Evidence(strategy, scope, [b], labels, starts)

    if strategy == "full":
        bib = _merge(
            [
                (r["char_start"], r["char_end"])
                for r in conn.execute(
                    "SELECT char_start, char_end FROM chunks WHERE text_sha256=?"
                    " AND is_bibliography=1",
                    (text_sha256,),
                )
            ]
        )
        blocks = []
        for r, p0 in zip(pages, starts, strict=True):
            p1 = p0 + len(r["text"])
            pieces, cur = [], p0
            for a, b in bib:
                if b <= cur or a >= p1:
                    continue
                if a > cur:
                    pieces.append((cur, a))
                cur = max(cur, b)
            if cur < p1:
                pieces.append((cur, p1))
            text, segs = "", []
            for a, b in pieces:
                if text:
                    text += " "
                segs.append((len(text), len(text) + (b - a), a))
                text += r["text"][a - p0 : b - p0]
            if text.strip():
                blocks.append(
                    Block(f"P{r['page_index']}", f"[[{tag_page(r['page_index'])}]]", text,
                          r["page_index"], None, segs)
                )  # fmt: skip
        return Evidence(strategy, scope, blocks, labels, starts)

    # passages
    chunks = {
        r["chunk_id"]: r
        for r in conn.execute(
            "SELECT * FROM chunks WHERE text_sha256=? AND is_bibliography=0 ORDER BY char_start",
            (text_sha256,),
        )
    }
    names, page_nums = locator_hints(prenote, postnote)
    priority: list[str] = []
    first = next(iter(chunks), None)
    if first:
        priority.append(first)
    for cid, r in chunks.items():
        pgs = {labels.get(p) for p in range(r["page_start"], r["page_end"] + 1)}
        if (names and _chunk_has_named(r["text"], names)) or (set(page_nums) & pgs):
            priority.append(cid)
    priority += [h.chunk_id for h in search_chunks(conn, text_sha256, query_text, limit=30)]
    chosen, used = [], 0
    for cid in dict.fromkeys(priority):
        cost = estimate_tokens(chunks[cid]["text"])
        if used + cost > passage_budget_tokens and chosen:
            continue
        chosen.append(cid)
        used += cost
    chosen.sort(key=lambda c: chunks[c]["char_start"])
    blocks = []
    for cid in chosen:
        r = chunks[cid]
        pg = (
            f"P{r['page_start']}"
            if r["page_start"] == r["page_end"]
            else f"P{r['page_start']}-{r['page_end']}"
        )
        blocks.append(
            Block(cid, f"[[C {cid} · {pg}]]", r["text"], r["page_start"], cid,
                  [(0, len(r["text"]), r["char_start"])])
        )  # fmt: skip
    return Evidence(strategy, scope, blocks, labels, starts)
