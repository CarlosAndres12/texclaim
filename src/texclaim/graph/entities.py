"""Entity extraction for the knowledge graph: methods, datasets, metrics, results, concepts."""

from __future__ import annotations

import json
import re

TYPES = ("method", "dataset", "metric", "task", "result", "concept")

ENTITY_SYSTEM = """\
You extract named entities from statements of a scientific manuscript to build a knowledge graph.
For each statement list the specific entities it mentions, with a type:
- method: models, algorithms, architectures, techniques (e.g. "Transformer", "dropout")
- dataset: datasets, corpora, benchmarks (e.g. "ImageNet", "WMT 2014 English-German")
- metric: evaluation measures (e.g. "BLEU", "top-5 error", "accuracy")
- task: problems or applications (e.g. "machine translation", "image classification")
- result: a reported value with its unit or metric (e.g. "28.4 BLEU", "3.57% top-5 error")
- concept: other key technical concepts (e.g. "residual connection", "overfitting")
Use canonical short names, keep the manuscript's language, skip generic words ("method", \
"results", "model", "approach"). At most 6 entities per statement.
Reply with JSON only: {"items": [{"id": <number>, "entities": [{"name": "...", "type": "..."}]}]}"""

_ACRONYM = re.compile(r"\b[A-Z][A-Za-z]*[A-Z][A-Za-z0-9\-]*\b")
_CAPS = re.compile(r"\b(?:[A-Z][a-z]+(?:[- ][A-Z][a-z]+)+)\b")
_RESULT = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:%|percent|por ciento|points?|puntos?|BLEU|F1|AUC|dB|ms|x)"
    r"(?:\s+(?:top-\d\s+)?(?:error|accuracy|precisión|exactitud))?",
    re.I,
)
_METRICS = {
    "bleu", "accuracy", "precision", "recall", "f1", "auc", "perplexity", "top-5 error",
    "top-1 error", "error rate", "rmse", "mae", "precisión", "exactitud", "exhaustividad",
}  # fmt: skip
_STOP = {
    "We", "Our", "The", "This", "These", "In", "Nuestro", "Nuestra", "Los", "Las", "El", "La",
    "Table", "Figure", "Section", "Tabla", "Figura", "Sección",
}  # fmt: skip


def norm_name(name: str) -> str:
    return " ".join(re.sub(r"[^\w%.\- ]", " ", name.lower()).split())


def heuristic_entities(text: str) -> list[dict]:
    """Cheap offline extraction: acronyms, capitalised phrases, values with units, metrics."""
    text = re.sub(r"\[@[^\]]*\]", " ", text)
    found: dict[str, dict] = {}

    def add(name: str, type_: str) -> None:
        n = name.strip(" .,;:")
        if len(n) < 2 or n in _STOP:
            return
        found.setdefault(norm_name(n), {"name": n, "type": type_})

    for m in _RESULT.finditer(text):
        add(m.group(0), "result")
    low = text.lower()
    for metric in _METRICS:
        if re.search(rf"\b{re.escape(metric)}\b", low):
            add(metric.upper() if metric in ("bleu", "f1", "auc") else metric, "metric")
    for m in _ACRONYM.finditer(text):
        if m.group(0).lower() not in _METRICS:
            add(m.group(0), "method")
    for m in _CAPS.finditer(text):
        if m.group(0).split()[0] not in _STOP:
            add(m.group(0), "concept")
    return list(found.values())[:6]


def entity_messages(items: list[tuple[str, str]]) -> list[dict]:
    body = "\n".join(f"{i}. {text}" for i, (_k, text) in enumerate(items, start=1))
    return [
        {"role": "system", "content": ENTITY_SYSTEM},
        {"role": "user", "content": f"STATEMENTS\n{body}"},
    ]


def parse_entities(raw: str, items: list[tuple[str, str]]) -> dict[str, list[dict]] | None:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    out: dict[str, list[dict]] = {k: [] for k, _ in items}
    for it in data.get("items", []):
        try:
            idx = int(it.get("id")) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= idx < len(items):
            continue
        ents = []
        for e in it.get("entities", [])[:6]:
            name = str(e.get("name", "")).strip()
            type_ = str(e.get("type", "concept")).lower()
            if name and len(name) <= 80:
                ents.append({"name": name, "type": type_ if type_ in TYPES else "concept"})
        out[items[idx][0]] = ents
    return out
