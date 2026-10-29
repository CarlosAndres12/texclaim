"""Length-preserving masking (PLAN §6.3): an offset in a masked text is the offset in the file."""

from __future__ import annotations

import re

FILL = "\ue000"

_BLANK_ENVS = r"verbatim\*?|Verbatim|lstlisting|minted|comment|alltt"
_ESC = re.compile(
    r"\\(?:begin\{(?P<env>" + _BLANK_ENVS + r")\}"
    r"|verb\*?(?P<delim>[^A-Za-z\s*])"
    r"|(?P<iffalse>iffalse)(?![A-Za-z]))"
)
_IF = re.compile(r"\\(if[A-Za-z]*|fi)(?![A-Za-z])")


def _blank(out: list[str], a: int, b: int) -> None:
    for k in range(a, b):
        if out[k] != "\n":
            out[k] = " "


def mask_comments(text: str) -> str:
    """Blank comments, comment/verbatim environments, \\verb and \\iffalse..\\fi blocks."""
    out = list(text)
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if c == "%":
            j = text.find("\n", i)
            j = n if j < 0 else j
            _blank(out, i, j)
            i = j
            continue
        if c == "\\":
            m = _ESC.match(text, i)
            if m is None:
                i += 2
                continue
            if m.group("env"):
                end_tag = "\\end{" + m.group("env") + "}"
                k = text.find(end_tag, m.end())
                end = n if k < 0 else k + len(end_tag)
            elif m.group("delim"):
                k = text.find(m.group("delim"), m.end())
                nl = text.find("\n", m.end())
                if k < 0 or (0 <= nl < k):
                    end = n if nl < 0 else nl
                else:
                    end = k + 1
            else:
                depth = 1
                end = n
                for t in _IF.finditer(text, m.end()):
                    name = t.group(1)
                    if name == "fi":
                        depth -= 1
                        if depth == 0:
                            end = t.end()
                            break
                    elif name != "iff":
                        depth += 1
            _blank(out, i, end)
            i = max(end, i + 1)
            continue
        i += 1
    return "".join(out)


_MATH_ENVS = "equation|align|alignat|gather|multline|flalign|eqnarray|displaymath|math|split"
_NO_BLANK_LINE = r"(?:(?!\n[ \t]*\n).)*?"
_MATH = re.compile(
    r"(?<!\\)\$\$.*?(?<!\\)\$\$"
    r"|(?<!\\)\$" + _NO_BLANK_LINE + r"(?<!\\)\$"
    r"|\\\(.*?\\\)"
    r"|\\\[.*?\\\]"
    r"|\\begin\{(" + _MATH_ENVS + r")(\*?)\}.*?\\end\{\1\2\}",
    re.S,
)
_REFS = re.compile(
    r"\\(?:ref|eqref|autoref|cref|Cref|pageref|nameref|vref|label)\*?\{[^}]*\}"
    r"|\\(?:url|href)\{[^}]*\}"
    r"|https?://[^\s}]+"
)


def opaque_spans(mask: str) -> list[tuple[int, int]]:
    """Math, references, labels and URLs: spans the sentence splitter must treat as one word."""
    spans = [m.span() for m in _MATH.finditer(mask)]
    spans += [m.span() for m in _REFS.finditer(mask)]
    return sorted(spans)


def fill(
    text: str, spans: list[tuple[int, int]], ch: str = FILL, keep_newlines: bool = False
) -> str:
    out = list(text)
    for a, b in spans:
        for k in range(max(a, 0), min(b, len(out))):
            if not (keep_newlines and out[k] == "\n"):
                out[k] = ch
    return "".join(out)
