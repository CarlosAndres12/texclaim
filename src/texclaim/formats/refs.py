"""Plain-text reference lists (numeric or author-year) turned into pandoc citations and BibTeX.

Word and Markdown manuscripts often have no .bib: citations are typed as `[1]`, `[2-4]` or
`(He et al., 2016)` and a "References" section lists the works. This module finds that section,
parses each entry into fields and rewrites the in-text citations as `[@refN]`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_HEADING = re.compile(
    r"^(?:#{1,6}\s*|\*\*)?\s*(?:\d+\.?\s*)?"
    r"(references|reference list|bibliography|works cited|literature cited|referencias"
    r"(?: bibliográficas)?|bibliografía|bibliografia)\s*(?:\*\*)?\s*:?\s*$",
    re.I,
)
_NEXT_HEADING = re.compile(r"^(#{1,6}\s+\S|(?:appendix|apéndice|anexo)s?\b)", re.I)
_ITEM = re.compile(r"^\s*(?:\[(\d+)\]|(\d+)[.)]|\\\[(\d+)\\\])\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+[^\s\"<>.,;)\]])", re.I)
_ARXIV = re.compile(r"arxiv[:\s]*(?:abs/)?(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I)
_YEAR = re.compile(r"\b(19[5-9]\d|20\d\d)[a-z]?\b")
_QUOTED = re.compile(r"[\"\u201c\u00ab]([^\"\u201d\u00bb]{8,}?)[\"\u201d\u00bb]")
_NUMERIC_CITE = re.compile(
    r"(?<![\w\]!])(?:\\?\[)((?:\d+(?:\s*[-\u2013]\s*\d+)?)(?:\s*,\s*\d+(?:\s*[-\u2013]\s*\d+)?)*)"
    r"(?:\\?\])(?![(:])"
)
_AY_PAREN = re.compile(r"\(([^()]*?\b(?:19|20)\d\d[a-z]?[^()]*?)\)")
_AY_PART = re.compile(
    r"^\s*(?:(?:see|e\.g\.|cf\.|véase|ver|p\. ej\.),?\s+)?"
    r"(?P<names>[A-ZÁÉÍÓÚÑÄÖÜ][\w'\u2019\-]+(?:\s+(?:et al\.|y col\.|and|&|y)\s*"
    r"(?:[A-ZÁÉÍÓÚÑÄÖÜ][\w'\u2019\-]+)?)?),?\s+(?P<year>(?:19|20)\d\d[a-z]?)\s*$"
)
_AY_NARRATIVE = re.compile(
    r"\b(?P<names>[A-ZÁÉÍÓÚÑÄÖÜ][\w'\u2019\-]+(?:\s+(?:et al\.|y col\.)|"
    r"\s+(?:and|&|y)\s+[A-ZÁÉÍÓÚÑÄÖÜ][\w'\u2019\-]+)?)\s+\((?P<year>(?:19|20)\d\d[a-z]?)\)"
)


@dataclass
class RefEntry:
    key: str
    number: int | None
    raw: str
    title: str | None = None
    year: str | None = None
    doi: str | None = None
    arxiv: str | None = None
    surnames: list[str] = field(default_factory=list)

    def bibtex(self) -> str:
        fields = {"title": self.title or self.raw[:200], "note": self.raw}
        if self.year:
            fields["year"] = self.year[:4]
        if self.surnames:
            fields["author"] = " and ".join(self.surnames)
        if self.doi:
            fields["doi"] = self.doi
        if self.arxiv:
            fields["eprint"] = self.arxiv
            fields["archiveprefix"] = "arXiv"
        body = ",\n".join(f"  {k} = {{{_bib_escape(v)}}}" for k, v in fields.items())
        return f"@misc{{{self.key},\n{body}\n}}\n"


def _bib_escape(s: str) -> str:
    s = s.replace("\\", " ").replace("{", "(").replace("}", ")")
    return re.sub(r"([%&#_$])", r"\\\1", s)


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _clean_md(s: str) -> str:
    s = re.sub(r"\\([\[\]@*_`#.])", r"\1", s)
    s = re.sub(r"[*_`]+", "", s)
    s = re.sub(r"<(https?://[^>]+)>", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 \2", s)
    return " ".join(s.split())


def parse_entry(raw: str, key: str, number: int | None) -> RefEntry:
    text = _clean_md(raw)
    e = RefEntry(key=key, number=number, raw=text)
    if m := _DOI.search(text):
        e.doi = m.group(1)
    if m := (_ARXIV.search(text) or _ARXIV_URL.search(text)):
        e.arxiv = m.group(1)
    if m := _YEAR.search(text):
        e.year = m.group(0)
    e.title = _guess_title(text)
    e.surnames = _guess_surnames(text)
    return e


_NAME = r"[A-Z\u00c0-\u00de][\w'\u2019\-]+"
_INITIALS = r"(?:[A-Z\u00c0-\u00de]\.\s*-?\s*)+"
_AUTHOR = (
    rf"(?:{_INITIALS}(?:(?:van|von|de|del|da|di|la|le)\s+)?{_NAME}"  # K. He
    rf"|{_NAME}(?:\s+{_NAME})?,\s*{_INITIALS}"  # He, K.
    rf"|{_NAME}\s+[A-Z]{{1,3}}(?=[,.;\s])"  # He K (Vancouver)
    rf"|{_NAME}(?:\s+{_INITIALS})?\s+{_NAME})"  # Kaiming He
)
_AUTHOR_BLOCK = re.compile(
    rf"^\s*(?P<a>{_AUTHOR})(?:\s*(?:,|;|,?\s*and|,?\s*&|,?\s*y)\s*{_AUTHOR})*"
    rf"(?:,?\s*(?:et\s+al\.?|y\s+col\.?))?"
)
_AUTHOR_ONE = re.compile(_AUTHOR)


def _author_block(text: str) -> tuple[list[str], int]:
    m = _AUTHOR_BLOCK.match(text)
    if not m:
        return [], 0
    names = []
    for a in _AUTHOR_ONE.finditer(m.group(0)):
        tok = a.group(0).strip(" ,.")
        if re.match(rf"^{_NAME}(?:\s+{_NAME})?,", tok):  # Surname, I.
            names.append(tok.split(",")[0].split()[-1])
        else:
            names.append(re.findall(_NAME, tok)[-1])
    return names, m.end()


def _guess_surnames(text: str) -> list[str]:
    return _author_block(text)[0][:6]


def _guess_title(text: str) -> str | None:
    if m := _QUOTED.search(text):
        return m.group(1).strip(" .,")
    t = re.sub(r"https?://\S+|doi:\s*\S+|arxiv:\s*\S+", "", text, flags=re.I)
    _names, end = _author_block(t)
    rest = t[end:]
    rest = re.sub(
        r"^[\s.,:]*(?:\(\s*(?:19|20)\d\d[a-z]?\s*\)|(?:19|20)\d\d[a-z]?)?[\s.,:]*", "", rest
    )
    title = re.split(r"\.\s+|\?\s+(?=[A-Z])", rest, maxsplit=1)[0].strip(" .,")
    return title if len(title) >= 8 else None


@dataclass
class RefSection:
    start: int  # line index of the heading
    end: int  # exclusive line index
    entries: list[RefEntry]


def find_reference_section(lines: list[str]) -> RefSection | None:
    idx = None
    for i, line in enumerate(lines):
        if _HEADING.match(line.strip()) and i > len(lines) * 0.2:
            idx = i
    if idx is None:
        return None
    end = len(lines)
    for j in range(idx + 1, len(lines)):
        if _NEXT_HEADING.match(lines[j].strip()) and not _ITEM.match(lines[j]):
            end = j
            break
    entries: list[RefEntry] = []
    cur: list[str] = []
    cur_num: int | None = None

    def flush() -> None:
        nonlocal cur, cur_num
        if cur:
            n = len(entries) + 1
            num = cur_num if cur_num is not None else n
            entries.append(parse_entry(" ".join(cur), f"ref{num}", num))
        cur, cur_num = [], None

    for line in lines[idx + 1 : end]:
        if not line.strip():
            flush()
            continue
        m = _ITEM.match(line)
        b = _BULLET.match(line)
        if m:
            flush()
            cur_num = int(next(g for g in m.groups()[:3] if g))
            cur = [m.group(4)]
        elif b:
            flush()
            cur = [b.group(1)]
        else:
            cur.append(line.strip())
    flush()
    return RefSection(idx, end, entries) if entries else None


def _expand(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if m := re.match(r"(\d+)\s*[-\u2013]\s*(\d+)", part):
            a, b = int(m.group(1)), int(m.group(2))
            if 0 < b - a < 50:
                out.extend(range(a, b + 1))
                continue
        if part.isdigit():
            out.append(int(part))
    return out


def _ay_lookup(entries: list[RefEntry]) -> dict[tuple[str, str], str]:
    table: dict[tuple[str, str], str] = {}
    for e in entries:
        if e.surnames and e.year:
            table.setdefault((fold(e.surnames[0]), e.year[:4]), e.key)
            table.setdefault((fold(e.surnames[0]), e.year), e.key)
    return table


def _first_surname(names: str) -> str:
    return fold(re.split(r"\s+(?:et\s+al\.?|y\s+col\.?|and|&|y)(?=\s|$)", names)[0].strip())


def rewrite_citations(body: str, entries: list[RefEntry]) -> tuple[str, int]:
    """Replace numeric and author-year citations that match an entry with `[@refN]`."""
    by_num = {e.number: e.key for e in entries if e.number is not None}
    ay = _ay_lookup(entries)
    count = 0

    def numeric(m: re.Match) -> str:
        nonlocal count
        nums = _expand(m.group(1))
        keys = [by_num[n] for n in nums if n in by_num]
        if not keys or len(keys) != len(nums):
            return m.group(0)
        count += 1
        return "[" + "; ".join(f"@{k}" for k in keys) + "]"

    def paren(m: re.Match) -> str:
        nonlocal count
        keys = []
        for part in m.group(1).split(";"):
            pm = _AY_PART.match(part)
            if not pm:
                return m.group(0)
            k = ay.get((_first_surname(pm.group("names")), pm.group("year")))
            if not k:
                return m.group(0)
            keys.append(k)
        count += 1
        return "[" + "; ".join(f"@{k}" for k in keys) + "]"

    def narrative(m: re.Match) -> str:
        nonlocal count
        k = ay.get((_first_surname(m.group("names")), m.group("year")))
        if not k:
            return m.group(0)
        count += 1
        return f"{m.group('names')} [@{k}]"

    if by_num:
        body = _NUMERIC_CITE.sub(numeric, body)
    if ay:
        body = _AY_PAREN.sub(paren, body)
        body = _AY_NARRATIVE.sub(narrative, body)
    return body, count


def convert_reference_list(markdown: str) -> tuple[str, str] | None:
    """(markdown without the reference list and with rewritten citations, bibtex) or None."""
    lines = markdown.splitlines()
    sec = find_reference_section(lines)
    if sec is None:
        return None
    body_lines = lines[: sec.start] + [""] * (sec.end - sec.start) + lines[sec.end :]
    body, n = rewrite_citations("\n".join(body_lines), sec.entries)
    if n == 0:
        return None
    return body, "\n".join(e.bibtex() for e in sec.entries)
