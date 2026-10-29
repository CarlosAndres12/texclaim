"""A scripted verifier for tests (PLAN §0 rule 7)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable

from texclaim.models import Quote, VerifierOutput
from texclaim.verifier.llm_client import ProviderError, VerifierCall, VerifyRequest

Responder = Callable[[VerifyRequest], "VerifierOutput | dict | str"]


def first_sentence(text: str, limit: int = 120) -> str:
    s = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return s[:limit]


def default_output(req: VerifyRequest) -> VerifierOutput:
    """SUPPORTED with a quote copied from the first block."""
    block = req.evidence.blocks[0]
    return VerifierOutput(
        citation_function="SUPPORTS_CLAIM",
        claim_scope="the whole sentence",
        quotes=[Quote(block_id=block.id, text=first_sentence(block.text))],
        analysis="The quote supports the claim.",
        verdict="SUPPORTED",
        reason_code="NONE",
        what_is_wrong=None,
        what_source_says=None,
        suggested_fix=None,
        confidence="high",
    )


class FakeVerifier:
    """Counts calls; `responder` maps a request to an output, a dict, or raw text."""

    model = "fake/model"

    def __init__(
        self,
        responder: Responder | None = None,
        *,
        cost: float | None = 0.001,
        delay: float = 0.0,
        fail_keys: set[str] | None = None,
    ) -> None:
        self.responder = responder or default_output
        self.cost, self.delay = cost, delay
        self.fail_keys = fail_keys or set()
        self.calls = 0
        self.requests: list[VerifyRequest] = []
        self.translations: list[tuple[str, str]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def verify(self, request: VerifyRequest) -> VerifierCall:
        self.calls += 1
        self.requests.append(request)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if request.unit.bib_key in self.fail_keys:
                raise ProviderError("simulated provider failure")
            res = self.responder(request)
            if isinstance(res, str):
                return VerifierCall(None, res, 100, 50, self.cost, error="invalid JSON")
            out = res if isinstance(res, VerifierOutput) else VerifierOutput.model_validate(res)
            return VerifierCall(out, out.model_dump_json(), 100, 50, self.cost)
        finally:
            self.in_flight -= 1

    async def translate(self, text: str, language: str) -> str:
        self.translations.append((text, language))
        return f"[{language}] {text}"
