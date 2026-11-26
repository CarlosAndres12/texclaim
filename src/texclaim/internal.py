"""Internal claims: uncited statements checked against the manuscript itself.

The manuscript becomes a pseudo-source with key `@self` (pages = top-level sections), so units,
evidence retrieval, quote verification and reports work exactly as for cited works. Candidate
sentences are screened for check-worthiness (by the model in batches, or by heuristics) and the
verdicts are cached in `internal_screen`.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable

from texclaim.config import InternalSettings
from texclaim.parser import ParseResult
from texclaim.parser.claim_extractor import SELF_KEY
from texclaim.sources.extractor import ExtractedDoc, Page
from texclaim.sources.locator import SourceResult

__all__ = ["SELF_KEY", "build_self_doc", "self_result", "heuristic_worthy", "section_selected"]

SCREEN_VERSION = 1

_WORTHY = re.compile(
    r"\d|%|\b(we (show|find|found|demonstrate|prove|observe|obtain|achieve|report|conclude)"
    r"|our (results|method|model|approach|experiments|analysis|findings)"
    r"|outperform|improv|increase|decrease|reduc|higher|lower|better|worse|faster|slower"
    r"|significant|first|best|state[- ]of[- ]the[- ]art|always|never|all|every|consistently"
    r"|demonstrat|confirm|prove|evidence|shows?|suggests?|indicates?|leads? to|causes?"
    r"|mostramos|demostramos|encontramos|obtenemos|nuestro|nuestros|nuestra|mejora|aument"
    r"|disminu|reduc|mayor|menor|mejor|peor|significativ|primer|siempre|nunca|todos"
    r"|concluimos|confirma|evidencia|muestra|sugiere|indica)\b",
    re.I,
)
_NOT_WORTHY = re.compile(
    r"^(in this (paper|work|section|article)|the rest of|this (paper|section) is organized"
    r"|en este (trabajo|art[ií]culo|cap[ií]tulo)|el resto|section \d|la secci[oó]n)",
    re.I,
)


def heuristic_worthy(text: str) -> bool:
    t = text.strip()
    if _NOT_WORTHY.search(t):
        return False
    return bool(_WORTHY.search(t))


def section_selected(section_path: str, role: str, wanted: Iterable[str]) -> bool:
    wanted = [w.strip().lower() for w in wanted if w.strip()]
    if not wanted:
        return True
    path = (section_path or "").lower()
    for w in wanted:
        if w in ("abstract", "resumen") and role == "abstract":
            return True
        if w in ("conclusion", "conclusions", "conclusiones", "conclusión") and (
            role == "conclusion"
        ):
            return True
        if w in path:
            return True
    return False


def top_section(path: str, role: str) -> str:
    if role == "abstract" and not path:
        return "Abstract"
    return (path or "").split(" > ")[0].strip() or "Front matter"


def build_self_doc(parsed: ParseResult) -> ExtractedDoc | None:
    """One page per top-level section, holding each paragraph once, in manuscript order."""
    sections: dict[str, list[str]] = {}
    seen: set[str] = set()
    claims = sorted(parsed.claims, key=lambda c: (c.file_path, c.char_start))
    order = {f.path: i for i, f in enumerate(parsed.files)}
    claims.sort(key=lambda c: (order.get(c.file_path, 1 << 30), c.char_start))
    for c in claims:
        para = _clean(c.para_norm or c.text_norm)
        if not para or para in seen:
            continue
        seen.add(para)
        sections.setdefault(top_section(c.section_path, c.role), []).append(para)
    if not sections:
        return None
    pages = [
        Page(i, title[:40], f"{title}\n\n" + "\n\n".join(paras))
        for i, (title, paras) in enumerate(sections.items(), start=1)
    ]
    return ExtractedDoc(pages, {"manuscript": True})


def _clean(text: str) -> str:
    """Citation markers out: the model should judge the manuscript's own statements."""
    return " ".join(re.sub(r"\s*\[@[^\]]*\]", "", text).split())


def self_result(conn: sqlite3.Connection, doc: ExtractedDoc, language: str | None) -> SourceResult:
    from texclaim.db.source_store import store_doc

    sha = store_doc(conn, doc)
    return SourceResult(
        SELF_KEY, "FULL_TEXT", provider="manuscript", version="self", text_sha256=sha,
        language=language,
    )  # fmt: skip


# ---- screening ----------------------------------------------------------------------------
def screen_key(text: str) -> str:
    return hashlib.sha256(f"{SCREEN_VERSION}\0{text}".encode()).hexdigest()


def cached_screen(conn: sqlite3.Connection, texts: list[str]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for t in texts:
        r = conn.execute(
            "SELECT worthy FROM internal_screen WHERE text_hash=?", (screen_key(t),)
        ).fetchone()
        if r is not None:
            out[t] = bool(r["worthy"])
    return out


def store_screen(conn: sqlite3.Connection, decisions: dict[str, bool], method: str) -> None:
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO internal_screen(text_hash, worthy, method) VALUES (?,?,?)",
            [(screen_key(t), int(w), method) for t, w in decisions.items()],
        )


SCREEN_SYSTEM = """\
You select statements in a scientific manuscript that make a checkable claim: a result, a number, \
a comparison, a causal or general assertion, or a conclusion that the rest of the manuscript \
should support. Skip roadmap sentences ("In Section 3 we..."), definitions, descriptions of \
what will be done, and generic background. Reply with JSON only: {"worthy": [list of numbers]}."""


def screen_messages(texts: list[str]) -> list[dict]:
    body = "\n".join(f"{i}. {t}" for i, t in enumerate(texts, start=1))
    return [
        {"role": "system", "content": SCREEN_SYSTEM},
        {"role": "user", "content": f"STATEMENTS\n{body}"},
    ]


def parse_screen(raw: str, n: int) -> set[int] | None:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return {int(i) for i in data.get("worthy", []) if 1 <= int(i) <= n}
    except (ValueError, TypeError, AttributeError):
        return None


async def screen(
    conn: sqlite3.Connection,
    texts: list[str],
    settings: InternalSettings,
    verifier=None,
    batch: int = 30,
) -> tuple[dict[str, bool], float]:
    """Decisions for `texts` (cached, then model, then heuristics). Returns (decisions, cost)."""
    texts = list(dict.fromkeys(texts))
    if settings.screening == "none":
        return {t: True for t in texts}, 0.0
    decisions = cached_screen(conn, texts)
    todo = [t for t in texts if t not in decisions]
    # Cheap prefilter: sentences with no claim signal at all never reach the model
    pre = {t: heuristic_worthy(t) for t in todo}
    cost = 0.0
    use_llm = settings.screening in ("auto", "llm") and hasattr(verifier, "screen")
    if use_llm:
        candidates = [t for t in todo if pre[t]]
        llm: dict[str, bool] = {t: False for t in todo if not pre[t]}
        for i in range(0, len(candidates), batch):
            chunk = candidates[i : i + batch]
            picked, c = await verifier.screen(chunk)
            cost += c or 0.0
            if picked is None:  # unparsable: fall back to heuristics for this batch
                llm.update({t: pre[t] for t in chunk})
            else:
                llm.update({t: (j in picked) for j, t in enumerate(chunk, start=1)})
        store_screen(conn, llm, "llm")
        decisions.update(llm)
    else:
        store_screen(conn, pre, "heuristic")
        decisions.update(pre)
    return decisions, cost


_ROLE_RANK = {"conclusion": 0, "abstract": 1, "": 2}


def select_units(
    conn: sqlite3.Connection, units: list, settings: InternalSettings, verifier=None
) -> tuple[list, dict]:
    """Keep cited units; keep internal units in the chosen sections that pass screening."""
    import asyncio

    internal = [u for u in units if getattr(u, "origin", "cited") == "internal"]
    if not internal:
        return units, {"candidates": 0, "kept": 0, "cost": 0.0}
    chosen = [u for u in internal if section_selected(u.section_path, u.role, settings.sections)]
    decisions, cost = asyncio.run(screen(conn, [u.text_norm for u in chosen], settings, verifier))
    kept = [u for u in chosen if decisions.get(u.text_norm)]
    kept.sort(key=lambda u: (_ROLE_RANK.get(u.role, 2), u.order))
    kept = kept[: settings.max_claims]
    keep_keys = {u.unit_key for u in kept}
    out = [u for u in units if u.origin != "internal" or u.unit_key in keep_keys]
    return out, {"candidates": len(chosen), "kept": len(kept), "cost": cost}
