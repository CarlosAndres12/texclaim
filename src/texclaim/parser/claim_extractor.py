"""Text units, sentences, claims and citation records (PLAN §6.5, §6.6)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from texclaim.models import CitationRec, ClaimRec, Diagnostic, SourceFile
from texclaim.parser.citations import CiteOccurrence, find_citations, find_definitions
from texclaim.parser.latex_graph import section_path
from texclaim.parser.masking import FILL, fill, mask_comments, opaque_spans
from texclaim.parser.tex import LineIndex, is_escaped, match_group, skip_space
from texclaim.parser.text import collapse, latex_to_text

ABBREVIATIONS = [
    "et al.", "e.g.", "i.e.", "cf.", "vs.", "resp.", "approx.", "fig.", "figs.", "eq.", "eqs.",
    "sec.", "secs.", "tab.", "ref.", "refs.", "thm.", "def.", "prop.", "lem.", "ch.", "app.",
    "no.", "pp.", "p.", "vol.", "dr.", "prof.",
    "p. ej.", "ec.", "cap.", "pág.", "aprox.", "etc.",
]  # fmt: skip

_BOUNDARY = re.compile(r"[.?!]+[)\]}\"'\u201d\u2019\u00bb]*(?=\s)")
_SPECIAL = re.compile(
    r"\\(?P<fn>footnotetext|footnote)(?![A-Za-z])"
    r"|\\(?P<cap>captionof|caption)(?![A-Za-z])\*?"
    r"|\\begin\{(?P<tab>tabular\*?|tabularx|tabulary|longtable|supertabular)\}"
    r"|\\begin\{(?P<bib>thebibliography)\}"
)
_INCLUDES = (
    r"\\(?:input|include|subfile)\*?\{[^}]*\}|\\(?:sub)?import\*?\{[^}]*\}\{[^}]*\}"
    r"|\\(?:maketitle|(?:title|author|date|thanks)\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})"
)
_MATH_ENV = re.compile(
    r"\\(?:begin|end)\{(?:equation|align|alignat|gather|multline|flalign|eqnarray|displaymath|math|split)\*?\}"
)
_BREAK = re.compile(
    r"\\(?:begin|end)\{[^}]*\}"
    r"|\\(?:part|chapter|(?:sub){0,2}section|(?:sub)?paragraph)\*?\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}"
    r"|" + _INCLUDES
)
_NOISE = _BREAK
_ITEM = re.compile(r"\\item(?![A-Za-z])")
_BLANK_LINE = re.compile(r"\n[ \t\r]*\n")
_RULES = re.compile(
    r"\\(?:hline|toprule|midrule|bottomrule|cline\{[^}]*\}|cmidrule(?:\([^)]*\))?\{[^}]*\})"
)
_TRAILING = re.compile(r"^[\s.,;:!?)\]}\u201d\"'\u00bb]*$")
_REFCMD = re.compile(r"\\(?:ref|eqref|autoref|cref|Cref|pageref|nameref|vref)\*?\{[^}]*\}")
_LABEL = re.compile(r"\\label\{[^}]*\}")
_DOC = re.compile(r"\\begin\{document\}")
_ENDDOC = re.compile(r"\\end\{document\}")


@dataclass
class Special:
    kind: str  # footnote | caption | table | bibliography
    start: int
    end: int
    c_start: int
    c_end: int


@dataclass
class ExtractResult:
    claims: list[ClaimRec] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    nocite_keys: list[tuple[str, str, int]] = field(default_factory=list)


def find_specials(mask: str, a: int, b: int) -> list[Special]:
    """Top-level footnotes, captions, tables and bibliographies in mask[a:b]."""
    out: list[Special] = []
    pos = a
    while True:
        m = _SPECIAL.search(mask, pos, b)
        if m is None:
            return out
        if is_escaped(mask, m.start()):
            pos = m.end()
            continue
        sp = None
        if m.group("fn"):
            j = skip_space(mask, m.end())
            if j < b and mask[j] == "[":
                e = match_group(mask, j, "[")
                j = skip_space(mask, e) if e else j
            if j < b and mask[j] == "{" and (e := match_group(mask, j)):
                sp = Special("footnote", m.start(), e, j + 1, e - 1)
        elif m.group("cap"):
            j = skip_space(mask, m.end())
            if m.group("cap") == "captionof" and j < b and mask[j] == "{":
                e = match_group(mask, j)
                j = skip_space(mask, e) if e else j
            if j < b and mask[j] == "[":
                e = match_group(mask, j, "[")
                j = skip_space(mask, e) if e else j
            if j < b and mask[j] == "{" and (e := match_group(mask, j)):
                sp = Special("caption", m.start(), e, j + 1, e - 1)
        else:
            name = m.group("tab") or m.group("bib")
            end_tag = "\\end{" + name + "}"
            depth, k = 1, m.end()
            tag_re = re.compile(re.escape("\\begin{" + name + "}") + "|" + re.escape(end_tag))
            end = None
            for t in tag_re.finditer(mask, m.end(), b):
                depth += 1 if t.group(0).startswith("\\begin") else -1
                if depth == 0:
                    end = t.end()
                    k = t.start()
                    break
            if end is not None:
                if m.group("bib"):
                    sp = Special("bibliography", m.start(), end, m.end(), k)
                else:
                    j = m.end()
                    for _ in range(3 if name == "tabularx" or name.endswith("*") else 1):
                        j = skip_space(mask, j)
                        if j < k and mask[j] == "[":
                            e = match_group(mask, j, "[")
                            j = e if e else j
                        j = skip_space(mask, j)
                        if j < k and mask[j] == "{" and (e := match_group(mask, j)):
                            j = e
                    sp = Special("table", m.start(), end, j, k)
        if sp is None:
            pos = m.end()
            continue
        out.append(sp)
        pos = sp.end
    return out


def table_rows(mask: str, a: int, b: int) -> list[tuple[int, int]]:
    """Row ranges: split on top-level `\\\\`."""
    rows, start, j = [], a, a
    depth = 0
    while j < b:
        c = mask[j]
        if c == "\\":
            if mask[j : j + 2] == "\\\\" and depth == 0:
                rows.append((start, j))
                j += 2
                if j < b and mask[j] == "[":
                    e = match_group(mask, j, "[")
                    j = e if e else j
                start = j
                continue
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        j += 1
    rows.append((start, b))
    return [(s, e) for s, e in rows if mask[s:e].strip()]


def split_sentences(seg: str, starters: frozenset[int] = frozenset()) -> list[tuple[int, int]]:
    """Sentence ranges in a segmentation view (opaque spans are FILL characters)."""
    bounds = [0]
    low = seg.lower()
    for m in _BOUNDARY.finditer(seg):
        k = m.end()
        while k < len(seg) and seg[k].isspace():
            k += 1
        if k >= len(seg):
            continue
        c = seg[k]
        if not (c.isupper() or c.isdigit() or c in "\\\u00bf\u00a1" or k in starters):
            continue
        dot = seg.find(".", m.start(), m.end())
        if dot >= 0 and m.group(0)[0] == ".":
            prefix = low[: m.start() + 1]
            if any(
                prefix.endswith(ab)
                and (len(prefix) == len(ab) or not prefix[-len(ab) - 1].isalpha())
                for ab in ABBREVIATIONS
            ):
                continue
        bounds.append(k)
    bounds.append(len(seg))
    out = []
    for s, e in zip(bounds, bounds[1:], strict=False):
        while s < e and seg[s].isspace():
            s += 1
        while e > s and seg[e - 1].isspace():
            e -= 1
        if e > s:
            out.append((s, e))
    return out


class _Extractor:
    def __init__(self, sf: SourceFile, extra: set[str]) -> None:
        self.sf = sf
        self.text = sf.text
        self.mask = mask_comments(sf.text)
        self.lines = LineIndex(sf.text)
        scan = find_citations(self.mask, extra)
        self.cites: list[CiteOccurrence] = scan.occurrences
        self.res = ExtractResult()
        for code, detail, off in scan.diagnostics:
            self.res.diagnostics.append(
                Diagnostic(code, detail, "warning", sf.path, self.lines.line(off))
            )
        for key, off in scan.nocites:
            self.res.nocite_keys.append((key, sf.path, self.lines.line(off)))
        self.defs = [(d.start, d.end) for d in find_definitions(self.mask)]

    # ---- text normalisation -------------------------------------------------
    def normalize(
        self,
        a: int,
        b: int,
        cites: list[CiteOccurrence],
        holes: list[tuple[int, int]],
        table: bool = False,
    ) -> str:
        """text_norm of mask[a:b]: citations as [@k1; @k2], holes (footnotes etc.) removed."""
        repl: list[tuple[int, int, str]] = [(s, e, "") for s, e in holes if a <= s and e <= b]
        for c in cites:
            if a <= c.start and c.end <= b:
                repl.append((c.start, c.end, "[@" + "; @".join(c.keys) + "]"))
        s = self.mask
        out, pos = [], a
        for rs, re_, new in sorted(repl):
            if rs < pos:
                continue
            out.append(s[pos:rs])
            out.append(new)
            pos = re_
        out.append(s[pos:b])
        txt = "".join(out)
        txt = _REFCMD.sub("[ref]", txt)
        txt = _LABEL.sub("", txt)
        if table:
            txt = _RULES.sub("", txt)
            txt = re.sub(r"(?<!\\)&", " | ", txt)
        return latex_to_text(txt)

    # ---- claim construction ---------------------------------------------------
    def emit(
        self,
        ranges: list[tuple[int, int]],
        kind: str,
        cites: list[CiteOccurrence],
        holes: list[tuple[int, int]],
        table: bool = False,
    ) -> None:
        """ranges: sentences (or one unit) of one paragraph, in order."""
        norms = [
            self.normalize(a, b, [c for c in cites if a <= c.start < b], holes, table)
            for a, b in ranges
        ]
        for idx, (a, b) in enumerate(ranges):
            own = [c for c in cites if a <= c.start < b]
            if not own:
                continue
            ctx = " ".join(n for i, n in enumerate(norms) if abs(i - idx) == 1 and n)
            text_norm = norms[idx]
            prev = norms[idx - 1] if idx > 0 else ""
            claim = ClaimRec(
                claim_hash=hashlib.sha256(text_norm.encode()).hexdigest(),
                file_path=self.sf.path,
                line_start=self.lines.line(a),
                line_end=self.lines.line(max(a, b - 1)),
                char_start=a,
                char_end=b,
                section_path=section_path(self.sf, a),
                unit_kind=kind,
                raw_latex=self.text[a:b],
                text_norm=text_norm,
                context_norm=collapse(ctx),
                prev_norm=collapse(prev),
                para_norm=collapse(" ".join(n for n in norms if n)),
            )
            prev_end = a
            for ci, c in enumerate(own):
                last = ci == len(own) - 1
                if last and _TRAILING.match(self.mask[c.end : b]):
                    span = text_norm
                else:
                    span = self.normalize(prev_end, c.start, [], holes, table)
                prev_end = c.end
                span = span or text_norm  # a citation opening the sentence: no preceding text
                pre = latex_to_text(c.prenote) if c.prenote is not None else None
                post = latex_to_text(c.postnote) if c.postnote is not None else None
                for key in c.keys:
                    claim.citations.append(
                        CitationRec(
                            bib_key=key,
                            cite_command=self.text[c.start : c.end],
                            prenote=pre or None,
                            postnote=post or None,
                            group_keys=sorted(set(c.keys)),
                            attributed_span=span,
                            char_start=c.start,
                            char_end=c.end,
                        )
                    )
            self.res.claims.append(claim)

    def process(self, a: int, b: int, kind: str, single: bool = False, table: bool = False) -> None:
        mask = self.mask
        specials = find_specials(mask, a, b)
        defs = [(s, e) for s, e in self.defs if a <= s < b]
        holes = [(sp.start, sp.end) for sp in specials] + defs
        own = [
            c
            for c in self.cites
            if a <= c.start < b and not any(s <= c.start < e for s, e in holes)
        ]
        bib = [sp for sp in specials if sp.kind == "bibliography"]
        for sp in specials:
            if sp.kind == "footnote":
                self.process(sp.c_start, sp.c_end, "footnote")
            elif sp.kind == "caption":
                self.process(sp.c_start, sp.c_end, "caption")
            elif sp.kind == "table":
                for rs, re_ in table_rows(mask, sp.c_start, sp.c_end):
                    self.process(rs, re_, "table_row", single=True, table=True)
        if bib:
            holes += [(s.start, s.end) for s in bib]
        if not own:
            return
        work = fill(mask[a:b], [(s - a, e - a) for s, e in holes if s < b and e > a])
        if single:
            ws = len(work) - len(work.lstrip())
            we = len(work.rstrip())
            sub_holes = [(s, e) for s, e in holes if a <= s and e <= b]
            self.emit([(a + ws, a + we)], kind, own, sub_holes, table)
            return
        # paragraphs: blank lines and \item
        cuts = [0]
        item_starts = {m.start() for m in _ITEM.finditer(work)}
        cuts += [m.end() for m in _BLANK_LINE.finditer(work)]
        cuts += sorted(item_starts)
        for m in _BREAK.finditer(work):
            if not _MATH_ENV.fullmatch(m.group(0)):
                cuts += [m.start(), m.end()]
        cuts = sorted(set(cuts)) + [len(work)]
        for ps, pe in zip(cuts, cuts[1:], strict=False):
            para_cites = [c for c in own if a + ps <= c.start < a + pe]
            if not para_cites:
                continue
            piece = work[ps:pe]
            starts_item = ps in item_starts
            piece = _ITEM.sub(lambda m: " " * len(m.group(0)), piece)
            piece = _NOISE.sub(lambda m: " " * len(m.group(0)), piece)
            seg_spans = [(c.start - a - ps, c.end - a - ps) for c in para_cites]
            seg_spans += opaque_spans(piece.replace(FILL, " "))
            seg = fill(piece, seg_spans)
            starters = frozenset(c.start - a - ps for c in para_cites)
            ranges = [(a + ps + s, a + ps + e) for s, e in split_sentences(seg, starters)]
            unit_kind = kind if kind != "sentence" else ("item" if starts_item else "sentence")
            self.emit(ranges, unit_kind, para_cites, holes)


def extract_claims(sf: SourceFile, extra: set[str] | frozenset[str] = frozenset()) -> ExtractResult:
    ex = _Extractor(sf, set(extra))
    start, end = 0, len(ex.mask)
    d = _DOC.search(ex.mask)
    if d:
        start = d.end()
    e = _ENDDOC.search(ex.mask, start)
    if e:
        end = e.start()
    ex.process(start, end, "sentence")
    ex.res.claims.sort(key=lambda c: c.char_start)
    return ex.res
