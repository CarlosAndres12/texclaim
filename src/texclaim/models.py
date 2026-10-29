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
