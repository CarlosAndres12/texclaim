"""LiteLLM-backed verifier (PLAN §11.6)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from texclaim.models import Unit, VerifierOutput
from texclaim.verifier.evidence import Evidence


class ProviderError(RuntimeError):
    """The provider failed after retries; the unit is retried on the next run."""


@dataclass
class VerifyRequest:
    unit: Unit
    evidence: Evidence
    messages: list[dict]
    report_language: str = "en"
    attempt: int = 1


@dataclass
class VerifierCall:
    output: VerifierOutput | None
    raw: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    error: str | None = None  # unparsable output; the engine may retry once


class Verifier(Protocol):
    model: str | None

    async def verify(self, request: VerifyRequest) -> VerifierCall: ...

    async def translate(self, text: str, language: str) -> str: ...


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def parse_output(raw: str) -> VerifierOutput:
    text = _FENCE.sub("", raw.strip()).strip()
    try:
        return VerifierOutput.model_validate_json(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return VerifierOutput.model_validate(json.loads(m.group(0)))


@dataclass
class LiteLLMVerifier:
    model: str
    api_key: str | None = None
    timeout: int = 120
    num_retries: int = 3
    extra: dict = field(default_factory=dict)  # e.g. mock_response for tests

    def __post_init__(self) -> None:
        import litellm

        litellm.drop_params = True
        litellm.suppress_debug_info = True  # verbose logging could echo request headers
        self._litellm = litellm

    @property
    def supports_schema(self) -> bool:
        try:
            return bool(self._litellm.supports_response_schema(model=self.model))
        except Exception:  # noqa: BLE001 - unknown model
            return False

    @property
    def is_anthropic(self) -> bool:
        return self.model.startswith("anthropic/") or "claude" in self.model

    def context_window(self) -> int | None:
        try:
            info = self._litellm.get_model_info(self.model)
            return info.get("max_input_tokens") or None
        except Exception:  # noqa: BLE001
            return None

    def _kwargs(self) -> dict:
        kw = {
            "model": self.model,
            "temperature": 0,
            "seed": 0,
            "num_retries": self.num_retries,
            "timeout": self.timeout,
            **self.extra,
        }
        if self.api_key:
            kw["api_key"] = self.api_key
        return kw

    async def verify(self, request: VerifyRequest) -> VerifierCall:
        kw = self._kwargs()
        kw["messages"] = request.messages
        kw["response_format"] = VerifierOutput if self.supports_schema else {"type": "json_object"}
        try:
            resp = await self._litellm.acompletion(**kw)
        except Exception as e:  # noqa: BLE001 - provider errors are many; never log the key
            raise ProviderError(f"{type(e).__name__}: {str(e)[:200]}") from e
        raw = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        try:
            cost = self._litellm.completion_cost(completion_response=resp)
        except Exception:  # noqa: BLE001 - local or unknown models have no price
            cost = None
        call = VerifierCall(
            None, raw,
            getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None), cost,
        )  # fmt: skip
        try:
            call.output = parse_output(raw)
        except ValueError as e:
            call.error = f"invalid JSON for the schema: {str(e)[:200]}"
        return call

    async def translate(self, text: str, language: str) -> str:
        from texclaim.verifier.prompts import TRANSLATE_SYSTEM

        kw = self._kwargs()
        kw["messages"] = [
            {"role": "system", "content": TRANSLATE_SYSTEM.format(language=language)},
            {"role": "user", "content": text},
        ]
        try:
            resp = await self._litellm.acompletion(**kw)
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"{type(e).__name__}: {str(e)[:200]}") from e
        return resp.choices[0].message.content or ""
