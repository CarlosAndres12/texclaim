"""SciFact claim-abstract pairs as an external sanity check at abstract scope.

Point `--scifact DIR` at an unpacked SciFact release (corpus.jsonl and claims_dev.jsonl). Nothing is
downloaded automatically. Mapping: SUPPORT -> SUPPORTED, CONTRADICT -> CONTRADICTED, no evidence ->
UNCHECKABLE (the abstract cannot settle the claim).
"""

from __future__ import annotations

import json
from pathlib import Path

LABELS = {"SUPPORT": "SUPPORTED", "CONTRADICT": "CONTRADICTED"}


def load_scifact(directory: Path, limit: int | None = None) -> list[dict]:
    corpus = {}
    for line in (directory / "corpus.jsonl").read_text().splitlines():
        d = json.loads(line)
        corpus[d["doc_id"]] = " ".join(d["abstract"])
    items: list[dict] = []
    for line in (directory / "claims_dev.jsonl").read_text().splitlines():
        d = json.loads(line)
        evidence = d.get("evidence") or {}
        if evidence:
            for doc_id, ev in evidence.items():
                label = LABELS.get(ev[0]["label"])
                if label and int(doc_id) in corpus:
                    items.append(
                        _item(d["id"], d["claim"], int(doc_id), corpus[int(doc_id)], label)
                    )
                    break
        else:
            for doc_id in (d.get("cited_doc_ids") or [])[:1]:
                if doc_id in corpus:
                    items.append(_item(d["id"], d["claim"], doc_id, corpus[doc_id], "UNCHECKABLE"))
    return items[:limit] if limit else items


def _item(cid, claim: str, doc_id: int, abstract: str, label: str) -> dict:
    return {
        "id": f"scifact-{cid}-{doc_id}", "claim": claim, "key": f"doc{doc_id}",
        "source_id": f"scifact-{doc_id}", "source_text": abstract, "scope": "abstract",
        "label": label, "cite_command": f"\\cite{{doc{doc_id}}}",
    }  # fmt: skip
