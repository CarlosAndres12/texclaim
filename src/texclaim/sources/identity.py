"""Identity check: is this file the cited work? (PLAN §7.5)"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@dataclass
class IdentityResult:
    ok: bool
    score: float
    detail: str


def check_identity(
    first_pages: str, title: str | None, first_surname: str | None
) -> IdentityResult:
    if not title:
        return IdentityResult(True, 0.0, "no title in the .bib entry; identity not checked")
    text = norm(first_pages)
    if not text:
        return IdentityResult(True, 0.0, "no text on the first pages; identity not checked")
    t = norm(title)
    score = fuzz.partial_ratio(t, text)
    if score >= 85:
        return IdentityResult(True, score, "title found on first pages")
    tokens = {w for w in t.split() if len(w) > 2}
    overlap = len(tokens & set(text.split())) / len(tokens) if tokens else 0.0
    surname = norm(first_surname).split()[-1:] if first_surname else []
    if surname and surname[0] in text.split() and overlap >= 0.6:
        return IdentityResult(True, score, f"author surname and {overlap:.0%} of title tokens")
    return IdentityResult(False, score, f"title match {score:.0f}, token overlap {overlap:.0%}")


def first_pages_text(data: bytes, pages: int = 2) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    out = []
    for p in reader.pages[:pages]:
        try:
            out.append(p.extract_text() or "")
        except Exception:  # noqa: BLE001 - a broken page must not abort the check
            out.append("")
    return "\n".join(out)
