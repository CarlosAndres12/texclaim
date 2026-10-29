"""Perturb SUPPORTED units into units with a known label (PLAN §14)."""

from __future__ import annotations

import re
from collections.abc import Callable

NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(%?)(?![\w])")
COMPARATIVES = [
    ("outperforms", "underperforms"), ("underperforms", "outperforms"),
    ("higher", "lower"), ("lower", "higher"), ("more", "fewer"), ("fewer", "more"),
    ("increases", "decreases"), ("decreases", "increases"), ("improves", "degrades"),
    ("better", "worse"), ("worse", "better"), ("faster", "slower"), ("slower", "faster"),
    ("larger", "smaller"), ("smaller", "larger"),
]  # fmt: skip
QUALIFIERS = [
    r"\bapproximately\s+", r"\bonly\s+", r"\bon average\b,?\s*", r"\bin some cases\b,?\s*",
    r"\bat most\s+", r"\bat least\s+", r"\broughly\s+", r"\bpartially\s+", r"\busually\s+",
    r"\bmay\s+", r"\bcan\s+",
]  # fmt: skip
WIDENERS = [
    (r"\bsome\b", "all"), (r"\bmany\b", "all"), (r"\bmost\b", "all"), (r"\boften\b", "always"),
    (r"\bsometimes\b", "always"), (r"\bseveral\b", "every"), (r"\bfew\b", "all"),
]  # fmt: skip


def change_numbers(text: str) -> str | None:
    def bump(m: re.Match) -> str:
        v = float(m.group(1))
        new = v * 1.5 + 1 if v < 100 else v * 0.5
        shown = f"{new:.1f}" if "." in m.group(1) else str(int(round(new)))
        return shown + m.group(2)

    out, n = NUMBER.subn(bump, text, count=1)
    return out if n else None


def flip_comparative(text: str) -> str | None:
    for a, b in COMPARATIVES:
        if re.search(rf"\b{a}\b", text):
            return re.sub(rf"\b{a}\b", b, text, count=1)
    return None


def drop_qualifier(text: str) -> str | None:
    for q in QUALIFIERS:
        if re.search(q, text, flags=re.I):
            return re.sub(q, "", text, count=1, flags=re.I)
    return None


def widen_scope(text: str) -> str | None:
    for pat, repl in WIDENERS:
        if re.search(pat, text, flags=re.I):
            return re.sub(pat, repl, text, count=1, flags=re.I)
    return None


# kind -> (transformation, expected label)
TRANSFORMS: dict[str, tuple[Callable[[str], str | None], str]] = {
    "number": (change_numbers, "CONTRADICTED"),
    "comparative": (flip_comparative, "CONTRADICTED"),
    "qualifier": (drop_qualifier, "PARTIALLY_SUPPORTED"),
    "scope": (widen_scope, "PARTIALLY_SUPPORTED"),
}


def perturb_items(items: list[dict]) -> list[dict]:
    """New items from SUPPORTED ones. Each keeps the source; swapped-key items change it."""
    out: list[dict] = []
    supported = [i for i in items if i["label"] == "SUPPORTED"]
    for it in supported:
        for kind, (fn, label) in TRANSFORMS.items():
            new = fn(it["claim"])
            if new and new != it["claim"]:
                out.append(
                    {**it, "id": f"{it['id']}+{kind}", "claim": new, "label": label,
                     "perturbation": kind, "origin_id": it["id"]}
                )  # fmt: skip
    # swapped citation key: the claim now cites a different (off-topic) source
    for i, it in enumerate(supported):
        other = next((o for o in supported[i + 1 :] if o["source_id"] != it["source_id"]), None)
        if other:
            out.append(
                {**it, "id": f"{it['id']}+swap", "source_id": other["source_id"],
                 "key": other["key"], "source_text": other.get("source_text"),
                 "source_pdf": other.get("source_pdf"), "label": "NOT_FOUND",
                 "perturbation": "swap", "origin_id": it["id"]}
            )  # fmt: skip
    return out
