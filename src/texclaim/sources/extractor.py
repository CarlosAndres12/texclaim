"""PDF text extraction and normalisation (PLAN §8)."""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

SCANNED_MIN_CHARS = 200  # average characters per page below this means no text layer

_HEADING_LINE = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*\.?|[A-Z]\.)\s+[A-Z][^\n]{1,70}"
    r"|(?:\d+\.?\s+)?(?:references|bibliography|referencias|bibliograf[ií]a|abstract))\s*$",
    re.I,
)
_PAGE_NUMBER = re.compile(r"^\s*(\d{1,5})\s*$")


@dataclass
class Page:
    index: int  # 1-based PDF page
    label: str | None
    text: str


@dataclass
class ExtractedDoc:
    pages: list[Page]
    meta: dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    @property
    def text_sha256(self) -> str:
        return hashlib.sha256(self.full_text.encode("utf-8")).hexdigest()

    @property
    def page_spans(self) -> list[tuple[int, int]]:
        spans, pos = [], 0
        for p in self.pages:
            spans.append((pos, pos + len(p.text)))
            pos += len(p.text) + 2
        return spans

    @property
    def scanned(self) -> bool:
        return bool(self.meta.get("scanned"))

    def to_json(self) -> dict:
        return {
            "pages": [[p.index, p.label, p.text] for p in self.pages],
            "meta": self.meta,
            "text_sha256": self.text_sha256,
        }

    @classmethod
    def from_json(cls, d: dict) -> ExtractedDoc:
        return cls([Page(i, label, t) for i, label, t in d["pages"]], d.get("meta", {}))


class Extractor(Protocol):
    def extract(self, source: Path | bytes) -> ExtractedDoc: ...


def normalize_page(raw: str) -> str:
    """NFKC (expands ligatures), soft hyphens out, line-end hyphens joined, paragraphs kept."""
    t = unicodedata.normalize("NFKC", raw).replace("­", "")
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("‐", "-")
    t = re.sub(r"(\w)-\n(?=[a-z])", r"\1", t)
    lines: list[str] = []
    for line in t.split("\n"):
        if _HEADING_LINE.match(line):
            lines += ["", line.strip(), ""]
        else:
            lines.append(line)
    paras = re.split(r"\n\s*\n", "\n".join(lines))
    cleaned = (re.sub(r"\s+", " ", p).strip() for p in paras)
    return "\n\n".join(p for p in cleaned if p)


def abstract_doc(text: str) -> ExtractedDoc:
    return ExtractedDoc([Page(1, None, normalize_page(text))], {"abstract": True})


def _infer_labels(raw_pages: list[str], pypdf_labels: list[str]) -> list[str | None]:
    """Prefer real PageLabels; otherwise infer a constant offset from printed page numbers."""
    n = len(raw_pages)
    default = [str(i + 1) for i in range(n)]
    if pypdf_labels and list(pypdf_labels) != default:
        return list(pypdf_labels)
    offsets: Counter[int] = Counter()
    for i, raw in enumerate(raw_pages):
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        for ln in (lines[:1] + lines[-1:]) if lines else []:
            m = _PAGE_NUMBER.match(ln)
            if m:
                offsets[int(m.group(1)) - (i + 1)] += 1
                break
    if offsets:
        off, count = offsets.most_common(1)[0]
        if count >= max(2, n // 2):
            return [str(i + 1 + off) for i in range(n)]
    return default


class PypdfExtractor:
    def extract(self, source: Path | bytes) -> ExtractedDoc:
        from pypdf import PdfReader

        data = source if isinstance(source, bytes) else Path(source).read_bytes()
        reader = PdfReader(io.BytesIO(data))
        raw_pages = []
        for page in reader.pages:
            try:
                raw_pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - one bad page must not lose the document
                raw_pages.append("")
        try:
            labels = _infer_labels(raw_pages, list(reader.page_labels))
        except Exception:  # noqa: BLE001
            labels = [str(i + 1) for i in range(len(raw_pages))]
        pages = [Page(i + 1, labels[i], normalize_page(t)) for i, t in enumerate(raw_pages)]
        total = sum(len(p.text) for p in pages)
        scanned = not pages or total / len(pages) < SCANNED_MIN_CHARS
        return ExtractedDoc(pages, {"n_pages": len(pages), "scanned": scanned})


class FakeExtractor:
    """Returns canned documents keyed by source bytes; counts calls."""

    def __init__(self, docs: dict[bytes, ExtractedDoc] | None = None) -> None:
        self.docs = docs or {}
        self.calls = 0

    def extract(self, source: Path | bytes) -> ExtractedDoc:
        self.calls += 1
        data = source if isinstance(source, bytes) else Path(source).read_bytes()
        return self.docs[data]


def extract_cached(
    data: bytes, cache, extractor: Extractor | None = None
) -> tuple[str, ExtractedDoc]:
    """Extract `data`, reusing the global text cache keyed by (blob sha, EXTRACTOR_VERSION)."""
    from texclaim.versions import EXTRACTOR_VERSION

    blob_sha = hashlib.sha256(data).hexdigest()
    cached = cache.get_text(blob_sha, EXTRACTOR_VERSION)
    if cached:
        return blob_sha, ExtractedDoc.from_json(cached)
    doc = (extractor or PypdfExtractor()).extract(data)
    cache.put_text(blob_sha, EXTRACTOR_VERSION, doc.to_json())
    return blob_sha, doc
