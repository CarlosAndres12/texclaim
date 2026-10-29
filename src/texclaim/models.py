"""Plain data records shared across subsystems."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Diagnostic:
    """A parsing or integrity warning that becomes a report line, never a crash."""

    code: str
    detail: str
    severity: str = "warning"
    file: str | None = None
    line: int | None = None


@dataclass
class SourceFile:
    path: str  # relative to the paper folder
    kind: str  # tex | bib
    sha256: str
    size_bytes: int
    text: str = field(default="", repr=False)
    # (offset, section stack after the event); the stack is a tuple of (level, title)
    section_events: list[tuple[int, tuple[tuple[int, str], ...]]] = field(default_factory=list)
    entry_stack: tuple[tuple[int, str], ...] = ()


@dataclass
class Unit:
    """One verification unit: a (claim, cited key) pair plus what is known about its source."""

    unit_key: str
    bib_key: str
    claim_hash: str
    text_norm: str
    context_norm: str
    unit_kind: str
    section_path: str
    file_path: str
    line_start: int
    cite_command: str
    prenote: str | None
    postnote: str | None
    group_keys: list[str]
    attributed_span: str
    other_keys: list[str]
    source_status: str
    text_sha256: str | None
    source_language: str | None
    source_provider: str | None
    source_version: str | None
    strategy: str  # full | passages | abstract | none
    order: int = 0


@dataclass
class CitationRec:
    bib_key: str
    cite_command: str
    prenote: str | None
    postnote: str | None
    group_keys: list[str]
    attributed_span: str
    char_start: int
    char_end: int
    unit_key: str = ""


@dataclass
class ClaimRec:
    claim_hash: str
    file_path: str
    line_start: int
    line_end: int
    char_start: int
    char_end: int
    section_path: str
    unit_kind: str
    raw_latex: str
    text_norm: str
    context_norm: str
    citations: list[CitationRec] = field(default_factory=list)


# ---- verifier contract (PLAN §11.4) -------------------------------------------------------
from typing import Literal  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402


class Quote(BaseModel):
    block_id: str = Field(description="ID of the SOURCE block the quote is copied from")
    text: str = Field(description="Verbatim excerpt, at most 300 characters")


class VerifierOutput(BaseModel):
    # Reasoning fields come first: models generate fields in schema order.
    citation_function: Literal["SUPPORTS_CLAIM", "ATTRIBUTION", "POINTER"]
    claim_scope: str = Field(description="What this citation is responsible for, in one sentence")
    quotes: list[Quote] = Field(
        description="0 to 3 verbatim quotes that support or refute the claim"
    )
    analysis: str = Field(description="At most 120 words comparing the claim with the quotes")
    verdict: Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED", "NOT_FOUND", "UNCHECKABLE"]
    reason_code: Literal[
        "NONE", "INSUFFICIENT_EVIDENCE", "EVIDENCE_IN_FIGURE_OR_TABLE", "OFF_TOPIC_SOURCE", "OTHER"
    ]
    what_is_wrong: str | None
    what_source_says: str | None
    suggested_fix: str | None = Field(
        description="Minimal rewrite of the LaTeX sentence, citation commands kept"
    )
    confidence: Literal["low", "medium", "high"]
