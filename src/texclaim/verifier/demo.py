"""Offline demo verifier (`model = "demo"`): deterministic, varied verdicts with real quotes.

It never calls a provider. Verdicts are chosen from a hash of the unit key so the same manuscript
always gives the same report; quotes are copied from the evidence so they pass verification.
Meant for trying the web app and for end-to-end tests, never for real checking.
"""

from __future__ import annotations

import asyncio
import hashlib
import re

from texclaim.models import Quote, VerifierOutput
from texclaim.verifier.llm_client import VerifierCall, VerifyRequest

VERDICTS = [
    ("SUPPORTED", 50),
    ("PARTIALLY_SUPPORTED", 20),
    ("CONTRADICTED", 10),
    ("NOT_FOUND", 10),
    ("UNCHECKABLE", 10),
]

TEXT = {
    "en": {
        "SUPPORTED": "The quoted passage states the claim directly.",
        "PARTIALLY_SUPPORTED": "The source supports the core of the claim but not its full scope.",
        "CONTRADICTED": "The source reports a different result than the manuscript states.",
        "NOT_FOUND": "The available text does not address this claim.",
        "UNCHECKABLE": "The available evidence cannot settle this claim.",
        "wrong": "The claim is stronger than what the source reports (demo verdict).",
        "says": "The source describes a narrower result (demo verdict).",
        "fix": "Qualify the statement to match the source.",
    },
    "es": {
        "SUPPORTED": "El pasaje citado afirma directamente lo que dice la oración.",
        "PARTIALLY_SUPPORTED": "La fuente respalda la idea central, pero no todo su alcance.",
        "CONTRADICTED": "La fuente informa un resultado distinto al que afirma el manuscrito.",
        "NOT_FOUND": "El texto disponible no trata esta afirmación.",
        "UNCHECKABLE": "La evidencia disponible no permite decidir.",
        "wrong": "La afirmación es más fuerte que lo que reporta la fuente (veredicto demo).",
        "says": "La fuente describe un resultado más acotado (veredicto demo).",
        "fix": "Matice la afirmación para que coincida con la fuente.",
    },
}


def _pick(key: str) -> str:
    n = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 100
    acc = 0
    for v, w in VERDICTS:
        acc += w
        if n < acc:
            return v
    return "SUPPORTED"


def _quote(text: str, seed: str) -> str:
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if 30 <= len(s) <= 280]
    if not sentences:
        return text.strip()[:200]
    i = int(hashlib.sha256(seed.encode()).hexdigest()[:6], 16) % len(sentences)
    return sentences[i].strip()


class DemoVerifier:
    model = "demo"
    supports_schema = True

    def __init__(self, delay: float = 0.15) -> None:
        self.delay = delay

    def estimate_cost(self, _unit=None) -> float:
        return 0.0

    async def verify(self, request: VerifyRequest) -> VerifierCall:
        if self.delay:
            await asyncio.sleep(self.delay)
        u, ev = request.unit, request.evidence
        lang = "es" if request.report_language == "es" else "en"
        t = TEXT[lang]
        verdict = _pick(u.unit_key)
        if verdict == "NOT_FOUND" and ev.scope != "full_text":
            verdict = "UNCHECKABLE"
        blocks = [b for b in ev.blocks if b.text.strip()]
        quotes = []
        if blocks and verdict in ("SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED"):
            # Internal claims must not quote themselves: prefer a block without the statement
            cand = [b for b in blocks if u.text_norm[:40] not in b.text] or blocks
            b = cand[int(hashlib.sha256(u.unit_key.encode()).hexdigest()[:4], 16) % len(cand)]
            q = _quote(b.text, u.unit_key)
            if u.origin == "internal" and u.text_norm[:30] in q:
                verdict, q = "UNCHECKABLE", ""
            if q:
                quotes.append(Quote(block_id=b.id, text=q))
        flagged = verdict in ("PARTIALLY_SUPPORTED", "CONTRADICTED")
        out = VerifierOutput(
            citation_function="SUPPORTS_CLAIM",
            claim_scope=u.attributed_span[:200] or u.text_norm[:200],
            quotes=quotes,
            analysis=t[verdict],
            verdict=verdict,
            reason_code="OTHER" if verdict == "UNCHECKABLE" else "NONE",
            what_is_wrong=t["wrong"] if flagged else None,
            what_source_says=t["says"] if flagged or verdict == "NOT_FOUND" else None,
            suggested_fix=t["fix"] if flagged else None,
            confidence="medium",
        )
        return VerifierCall(out, out.model_dump_json(), 0, 0, 0.0)

    async def translate(self, text: str, language: str) -> str:
        return text

    async def extract_entities(self, items: list[tuple[str, str]]):
        from texclaim.graph.entities import heuristic_entities

        return {k: heuristic_entities(t) for k, t in items}, 0.0
