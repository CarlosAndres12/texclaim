import asyncio
import json

import pytest
from metrics import evaluate, release_bar, wilson
from perturb import (
    change_numbers,
    drop_qualifier,
    flip_comparative,
    perturb_items,
    widen_scope,
)
from run import load_gold, main, run_items, summarize
from scifact import load_scifact

from texclaim.config import Settings
from texclaim.models import VerifierOutput
from texclaim.verifier.fake import FakeVerifier, default_output

SRC = (
    "We evaluate on ImageNet. Our method reaches 84.2% accuracy without pretraining. "
    "Training uses 8 GPUs for two days and a cosine learning rate schedule with warmup. "
    "The model outperforms the baseline on average, and it may transfer to other datasets."
)


def item(i, label, claim="The method reaches 84.2% accuracy [@k].", key="k", src=SRC):
    return {
        "id": i,
        "claim": claim,
        "key": key,
        "source_id": key,
        "source_text": src,
        "label": label,
    }


def test_wilson_known_values():
    lo, hi = wilson(8, 10)
    assert (round(lo, 3), round(hi, 3)) == (0.49, 0.943)
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and 0.25 < hi < 0.30
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and 0.72 < lo < 0.73


def test_metrics_precision_recall_confusion():
    pairs = (
        [("SUPPORTED", "SUPPORTED")] * 8
        + [("SUPPORTED", "CONTRADICTED")] * 2
        + [("CONTRADICTED", "CONTRADICTED")] * 6
        + [("CONTRADICTED", "SUPPORTED")] * 2
        + [("NOT_FOUND", "UNCHECKABLE")]
    )
    m = evaluate(pairs)
    c = m["per_verdict"]["CONTRADICTED"]
    assert (c["precision"]["k"], c["precision"]["n"]) == (6, 8)
    assert (c["recall"]["k"], c["recall"]["n"]) == (6, 8)
    assert c["precision"]["value"] == 0.75
    assert m["confusion"]["SUPPORTED"] == {"SUPPORTED": 8, "CONTRADICTED": 2}
    assert m["false_alarm_rate"]["value"] == 0.2 and m["n"] == len(pairs)
    assert m["per_verdict"]["NOT_FOUND"]["precision"]["value"] is None  # never predicted
    bar = release_bar(m)
    assert not bar["pass"] and not bar["checks"]["contradicted_precision"]["pass"]
    good = release_bar(
        evaluate([("SUPPORTED", "SUPPORTED")] * 10 + [("CONTRADICTED", "CONTRADICTED")] * 5)
    )
    assert good["pass"]


def test_perturbations():
    assert change_numbers("It reaches 84.2% on 3 datasets.") != "It reaches 84.2% on 3 datasets."
    assert "84.2" not in change_numbers("It reaches 84.2% accuracy.")
    assert flip_comparative("A outperforms B.") == "A underperforms B."
    assert drop_qualifier("It only works approximately.") == "It works approximately."
    assert widen_scope("Some models fail.") == "all models fail."
    assert change_numbers("no digits here") is None and flip_comparative("neutral") is None


def test_perturb_items_labels_and_swap():
    base = [
        item("a", "SUPPORTED", "A outperforms B by 3.2% on average [@x].", "x"),
        item("b", "SUPPORTED", "Some models only work at night [@y].", "y", src="Night text."),
        item("c", "CONTRADICTED"),
    ]
    out = perturb_items(base)
    by = {o["id"]: o for o in out}
    assert (
        by["a+number"]["label"] == "CONTRADICTED" and by["a+comparative"]["label"] == "CONTRADICTED"
    )
    assert by["a+qualifier"]["label"] == "PARTIALLY_SUPPORTED"
    assert by["b+scope"]["label"] == "PARTIALLY_SUPPORTED"
    assert by["a+swap"]["label"] == "NOT_FOUND" and by["a+swap"]["source_text"] == "Night text."
    assert not any(o["origin_id"] == "c" for o in out)  # only SUPPORTED units are perturbed


def test_load_gold_skips_example_and_comments(tmp_path):
    (tmp_path / "example.jsonl").write_text(json.dumps(item("e", "SUPPORTED")) + "\n")
    (tmp_path / "mine.jsonl").write_text(
        "# comment\n"
        + json.dumps(
            {"id": "m", "claim": "c", "key": "k", "label": "SUPPORTED", "source_text": "t"}
        )
        + "\n"
    )
    got = load_gold(tmp_path)
    assert [g["id"] for g in got] == ["m"] and got[0]["source_id"] == "k"


def test_run_items_scores_a_scripted_model(tmp_path):
    def responder(req):
        o = default_output(req)
        if "outperforms" in req.unit.text_norm:
            return VerifierOutput(**{**o.model_dump(), "verdict": "CONTRADICTED",
                                     "what_is_wrong": "x", "what_source_says": "y"})  # fmt: skip
        return o

    items = [
        item("s1", "SUPPORTED"),
        item("c1", "CONTRADICTED", "The model outperforms the baseline by 9% [@k]."),
        item("s2", "SUPPORTED", "Training uses 8 GPUs [@k]."),
    ]
    rows = asyncio.run(run_items(items, FakeVerifier(responder), Settings(), tmp_path))
    assert [r["pred"] for r in rows] == ["SUPPORTED", "CONTRADICTED", "SUPPORTED"]
    s = summarize(rows)
    assert s["metrics"]["per_verdict"]["CONTRADICTED"]["precision"]["value"] == 1.0
    assert s["release_bar"]["pass"] and s["cost_per_unit_usd"] == pytest.approx(0.001)


def test_provider_errors_are_counted_not_fatal(tmp_path):
    rows = asyncio.run(
        run_items([item("e1", "SUPPORTED")], FakeVerifier(fail_keys={"k"}), Settings(), tmp_path)
    )
    assert rows[0]["pred"] == "ERROR" and summarize(rows)["errors"] == 1


def test_main_writes_results_file(tmp_path, capsys):
    gold = tmp_path / "gold"
    gold.mkdir()
    lines = [item(f"u{i}", "SUPPORTED", f"Training uses 8 GPUs, claim {i} [@k].") for i in range(3)]
    (gold / "g.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
    out = tmp_path / "results"
    code = main(["--model", "fake/model", "--gold", str(gold), "--out", str(out), "--fake",
                 "--perturb"])  # fmt: skip
    assert code == 0
    (path,) = out.glob("*-fake_model.json")
    res = json.loads(path.read_text())
    assert res["model"] == "fake/model" and res["n_items"] >= 3
    assert "per_verdict" in res["metrics"] and "release_bar" in res and res["rows"]
    assert "release bar:" in capsys.readouterr().out
    assert main(["--model", "m", "--gold", str(tmp_path / "empty"), "--fake"]) == 2


def test_scifact_loader(tmp_path):
    (tmp_path / "corpus.jsonl").write_text(
        "\n".join(
            json.dumps({"doc_id": i, "title": "t", "abstract": [f"Abstract {i}."]})
            for i in (1, 2, 3)
        )  # fmt: skip
    )
    claims = [
        {
            "id": 10,
            "claim": "A",
            "evidence": {"1": [{"sentences": [0], "label": "SUPPORT"}]},
            "cited_doc_ids": [1],
        },
        {
            "id": 11,
            "claim": "B",
            "evidence": {"2": [{"sentences": [0], "label": "CONTRADICT"}]},
            "cited_doc_ids": [2],
        },
        {"id": 12, "claim": "C", "evidence": {}, "cited_doc_ids": [3]},
    ]
    (tmp_path / "claims_dev.jsonl").write_text("\n".join(json.dumps(c) for c in claims))
    got = load_scifact(tmp_path)
    assert [g["label"] for g in got] == ["SUPPORTED", "CONTRADICTED", "UNCHECKABLE"]
    assert all(g["scope"] == "abstract" for g in got) and got[0]["source_text"] == "Abstract 1."
    rows = asyncio.run(run_items(got, FakeVerifier(), Settings(), tmp_path))
    assert all(r["pred"] == "SUPPORTED" for r in rows)  # fake always supports; plumbing only
