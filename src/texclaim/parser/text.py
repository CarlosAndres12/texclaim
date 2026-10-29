"""LaTeX to plain text with pylatexenc, tolerant of malformed input."""

from __future__ import annotations

import re
import unicodedata

from pylatexenc.latex2text import LatexNodes2Text

_L2T = LatexNodes2Text(math_mode="verbatim", keep_comments=False, strict_latex_spaces=False)


def collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def latex_to_text(s: str) -> str:
    try:
        out = _L2T.latex_to_text(s)
    except Exception:  # noqa: BLE001 - pylatexenc can fail on odd input; degrade to a regex strip
        out = re.sub(r"\\[A-Za-z]+\*?|[{}]", "", s)
    return collapse(unicodedata.normalize("NFC", out))
