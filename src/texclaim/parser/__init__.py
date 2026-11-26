"""LaTeX parsing: root discovery, include graph, citations, claims."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from texclaim.models import ClaimRec, Diagnostic, SourceFile
from texclaim.parser.citations import find_definitions
from texclaim.parser.claim_extractor import extract_claims
from texclaim.parser.latex_graph import BibResource, build_graph
from texclaim.parser.masking import mask_comments
from texclaim.parser.root_finder import find_root
from texclaim.parser.tex import LineIndex


@dataclass
class ParseResult:
    root: str
    files: list[SourceFile]
    claims: list[ClaimRec]
    diagnostics: list[Diagnostic]
    bib_resources: list[BibResource]
    nocite_keys: list[tuple[str, str, int]] = field(default_factory=list)  # key, file, line
    includeonly: bool = False


def parse_manuscript(
    paper: Path,
    main: str | Path | None = None,
    extra_cite_commands: list[str] | None = None,
    internal: bool = False,
) -> ParseResult:
    paper = paper.resolve()
    root = find_root(paper, main)
    graph = build_graph(paper, root)
    extra = {c.lower().lstrip("\\") for c in (extra_cite_commands or [])}
    diags = list(graph.diagnostics)
    wrappers: set[str] = set()
    for f in graph.files:
        lines = LineIndex(f.text)
        for d in find_definitions(mask_comments(f.text)):
            if d.is_wrapper:
                wrappers.add(d.name.lower())
                diags.append(
                    Diagnostic(
                        "UNKNOWN_CITE_MACRO",
                        f"\\{d.name} wraps a citation command; registered as a citation macro",
                        "info",
                        f.path,
                        lines.line(d.start),
                    )
                )
    claims: list[ClaimRec] = []
    nocites: list[tuple[str, str, int]] = []
    for f in graph.files:
        res = extract_claims(f, extra | wrappers, internal)
        claims.extend(res.claims)
        diags.extend(res.diagnostics)
        nocites.extend(res.nocite_keys)
    return ParseResult(
        root=graph.root_rel,
        files=graph.files,
        claims=claims,
        diagnostics=diags,
        bib_resources=graph.bib_resources,
        nocite_keys=nocites,
        includeonly=graph.includeonly,
    )
