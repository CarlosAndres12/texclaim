"""Evaluate verdict quality on a labeled gold set: `make eval MODEL=<model>` (PLAN §14).

Gold items (JSON lines in evals/gold/*.jsonl):
  id, claim (plain text of the sentence, citations as [@key]), key, source_id,
  source_text | source_pdf (path relative to evals/gold), label, optional prenote, postnote,
  cite_command, attributed_span, section, scope ("abstract" to force abstract evidence).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from metrics import evaluate, release_bar
from perturb import perturb_items

from texclaim.config import Settings
from texclaim.db.source_store import store_doc
from texclaim.db.state_store import open_db
from texclaim.models import Unit
from texclaim.planner import unit_key
from texclaim.sources.extractor import (
    ExtractedDoc,
    Page,
    PypdfExtractor,
    abstract_doc,
    normalize_page,
)
from texclaim.verifier.engine import verify_unit
from texclaim.verifier.evidence import choose_strategy, estimate_tokens

HERE = Path(__file__).resolve().parent


def load_gold(directory: Path) -> list[dict]:
    items = []
    for f in sorted(directory.glob("*.jsonl")):
        if f.name.startswith("example"):
            continue
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if line.strip() and not line.lstrip().startswith("#"):
                d = json.loads(line)
                d.setdefault("source_id", d["key"])
                d["_where"] = f"{f.name}:{n}"
                items.append(d)
    return items


def source_doc(item: dict, gold_dir: Path) -> ExtractedDoc:
    if item.get("source_text") is not None:
        text = item["source_text"]
        if item.get("scope") == "abstract":
            return abstract_doc(text)
        return ExtractedDoc([Page(1, None, normalize_page(text))], {})
    return PypdfExtractor().extract(gold_dir / item["source_pdf"])


async def run_items(items: list[dict], verifier, settings: Settings, gold_dir: Path) -> list[dict]:
    rows: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        conn = open_db(Path(tmp))
        shas: dict[str, tuple[str, str]] = {}
        for it in items:
            sid = it["source_id"] + ("|abs" if it.get("scope") == "abstract" else "")
            if sid not in shas:
                doc = source_doc(it, gold_dir)
                status = "ABSTRACT_ONLY" if it.get("scope") == "abstract" else "FULL_TEXT"
                shas[sid] = (store_doc(conn, doc), status)
            sha, status = shas[sid]
            chars = conn.execute(
                "SELECT COALESCE(SUM(LENGTH(text)),0) FROM source_pages WHERE text_sha256=?", (sha,)
            ).fetchone()[0]
            strategy = choose_strategy(
                status, estimate_tokens(chars), settings.evidence.strategy,
                settings.evidence.full_text_max_tokens,
            )  # fmt: skip
            span = it.get("attributed_span") or it["claim"]
            cmd = it.get("cite_command") or f"\\cite{{{it['key']}}}"
            unit = Unit(
                unit_key=unit_key(
                    claim_hash=hashlib.sha256(it["claim"].encode()).hexdigest(), bib_key=it["key"],
                    prenote=it.get("prenote"), postnote=it.get("postnote"), group_keys=[it["key"]],
                    attributed_span=span, source=sha, strategy=strategy,
                ),
                bib_key=it["key"], claim_hash=hashlib.sha256(it["claim"].encode()).hexdigest(),
                text_norm=it["claim"], context_norm=it.get("context", ""), unit_kind="sentence",
                section_path=it.get("section", ""), file_path=it["id"], line_start=1,
                cite_command=cmd, prenote=it.get("prenote"), postnote=it.get("postnote"),
                group_keys=[it["key"]], attributed_span=span, other_keys=[], source_status=status,
                text_sha256=sha, source_language=it.get("source_language"), source_provider=None,
                source_version=None, strategy=strategy,
            )  # fmt: skip
            t0 = time.perf_counter()
            try:
                rec = await verify_unit(unit, conn, verifier, settings)
                pred, cost, err = rec.verdict, rec.cost_usd, None
                reason, review = rec.reason_code, rec.needs_review
            except Exception as e:  # noqa: BLE001 - a provider failure must not abort the run
                pred, cost, err, reason, review = (
                    "ERROR",
                    None,
                    f"{type(e).__name__}: {e}"[:200],
                    "",
                    False,
                )
            rows.append(
                {"id": it["id"], "gold": it["label"], "pred": pred, "reason": reason,
                 "needs_review": review, "cost_usd": cost,
                 "seconds": round(time.perf_counter() - t0, 3),
                 "perturbation": it.get("perturbation"), "error": err}
            )  # fmt: skip
        conn.close()
    return rows


def summarize(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["pred"] != "ERROR"]
    m = evaluate([(r["gold"], r["pred"]) for r in ok])
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    by_kind: dict[str, list[dict]] = {}
    for r in ok:
        if r["perturbation"]:
            by_kind.setdefault(r["perturbation"], []).append(r)
    return {
        "metrics": m,
        "release_bar": release_bar(m),
        "errors": len(rows) - len(ok),
        "cost_per_unit_usd": (sum(costs) / len(costs)) if costs else None,
        "seconds_per_unit": (sum(r["seconds"] for r in rows) / len(rows)) if rows else None,
        "perturbation_recall": {
            k: {"detected": sum(r["pred"] == r["gold"] for r in v), "n": len(v)}
            for k, v in sorted(by_kind.items())
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--gold", type=Path, default=HERE / "gold")
    ap.add_argument("--perturb", action="store_true", help="add perturbations of SUPPORTED units")
    ap.add_argument("--scifact", type=Path, help="unpacked SciFact release directory")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", type=Path, default=HERE / "results")
    ap.add_argument("--fake", action="store_true", help="use the scripted FakeVerifier (self test)")
    args = ap.parse_args(argv)

    items = load_gold(args.gold)
    if args.scifact:
        from scifact import load_scifact

        items += load_scifact(args.scifact, args.limit)
    if args.perturb:
        items += perturb_items(items)
    if args.limit:
        items = items[: args.limit]
    if not items:
        print(f"no labeled items found in {args.gold}; see evals/gold/README.md", file=sys.stderr)
        return 2
    if args.fake:
        from texclaim.verifier.fake import FakeVerifier

        verifier = FakeVerifier()
    else:
        from texclaim.verifier.llm_client import LiteLLMVerifier

        verifier = LiteLLMVerifier(args.model)
    settings = Settings(model=args.model)
    rows = asyncio.run(run_items(items, verifier, settings, args.gold))
    result = {
        "model": args.model, "date": datetime.now(UTC).isoformat(), "n_items": len(items),
        "n_gold_units": sum(1 for i in items if "perturbation" not in i and "scope" not in i),
        **summarize(rows), "rows": rows,
    }  # fmt: skip
    args.out.mkdir(parents=True, exist_ok=True)
    safe = args.model.replace("/", "_").replace(":", "_")
    path = args.out / f"{datetime.now(UTC):%Y-%m-%d}-{safe}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    bar = result["release_bar"]
    print(f"wrote {path}")
    for name, c in bar["checks"].items():
        v = "n/a" if c["value"] is None else f"{c['value']:.2f}"
        print(f"{name}: {v} (n={c['n']}, 95% CI {c['ci95']}) -> {'pass' if c['pass'] else 'FAIL'}")
    print("release bar:", "PASS" if bar["pass"] else "NOT MET (numbers recorded either way)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
