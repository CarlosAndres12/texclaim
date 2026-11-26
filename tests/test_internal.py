import json

from typer.testing import CliRunner

from texclaim.check import CheckOptions, run_check
from texclaim.config import InternalSettings, load_settings
from texclaim.internal import (
    build_self_doc,
    heuristic_worthy,
    parse_screen,
    section_selected,
)
from texclaim.models import Quote, VerifierOutput
from texclaim.parser import parse_manuscript
from texclaim.parser.claim_extractor import section_role
from texclaim.reporting.write import write_reports
from texclaim.verifier.fake import FakeVerifier
from texclaim.verifier.validate import restates

TEX = r"""\documentclass{article}
\begin{document}
\begin{abstract}
We show that our model improves accuracy by 12 points over the baseline.
\end{abstract}
\section{Introduction}
Transformers are popular \cite{a}. In this paper we describe our approach in detail.
\section{Results}
Our model reaches 85\% accuracy while the baseline reaches 80\% on the test set.
\section{Conclusiones}
Our model improves accuracy by 12 points, which is a large gain overall.
\end{document}
"""


def _paper(tmp_path):
    (tmp_path / "main.tex").write_text(TEX)
    (tmp_path / "refs.bib").write_text("")
    return tmp_path


def test_extraction_roles(tmp_path):
    claims = parse_manuscript(_paper(tmp_path), internal=True).claims
    internal = [c for c in claims if c.origin == "internal"]
    roles = {c.text_norm[:20]: c.role for c in internal}
    assert roles["We show that our mod"] == "abstract"
    assert roles["Our model improves a"] == "conclusion"
    assert all(k.bib_key == "@self" for c in internal for k in c.citations)
    assert not [c for c in parse_manuscript(tmp_path).claims if c.origin == "internal"]


def test_self_doc_sections(tmp_path):
    doc = build_self_doc(parse_manuscript(_paper(tmp_path), internal=True))
    titles = [p.label for p in doc.pages]
    assert titles == ["Abstract", "Introduction", "Results", "Conclusiones"]
    assert "[@a]" not in doc.full_text


def test_heuristics_and_sections():
    assert heuristic_worthy("Our model reaches 85% accuracy.")
    assert not heuristic_worthy("In this paper we describe the approach.")
    assert section_role("Results > Conclusions") == "conclusion"
    assert section_selected("Results > Ablation", "", ["ablation"])
    assert section_selected("", "abstract", ["abstract"])
    assert not section_selected("Introduction", "", ["results", "conclusion"])
    assert section_selected("Introduction", "", [])
    assert parse_screen('{"worthy": [1, 3, 9]}', 3) == {1, 3}
    assert parse_screen("nonsense", 3) is None


def test_restates():
    st = "Our model improves accuracy by 12 points, which is a large gain overall."
    assert restates("Our model improves accuracy by 12 points", st)
    assert not restates("the baseline reaches 80% on the test set", st)


def _contradicts(req):
    u = req.unit
    if u.bib_key != "@self":
        raise AssertionError("only internal units expected")
    block = next(b for b in req.evidence.blocks if "85" in b.text)
    i = block.text.index("Our model reaches")
    return VerifierOutput(
        citation_function="SUPPORTS_CLAIM", claim_scope="s",
        quotes=[Quote(block_id=block.id, text=block.text[i : i + 60])],
        analysis="5 points, not 12.", verdict="CONTRADICTED", reason_code="NONE",
        what_is_wrong="12 points", what_source_says="85 vs 80", suggested_fix=None,
        confidence="high",
    )  # fmt: skip


def test_check_internal_end_to_end(tmp_path):
    paper = _paper(tmp_path)
    settings = load_settings(paper, cli={"model": "fake/model", "offline": True})
    settings.internal = InternalSettings(sections=["abstract", "conclusion"])
    fake = FakeVerifier(_contradicts)
    out = run_check(paper, settings, fake, CheckOptions())
    texts = sorted(r.unit.text_norm[:12] for r in fake.requests)
    assert texts == ["Our model im", "We show that"]
    assert "STATEMENT (uncited)" in fake.requests[0].messages[1]["content"]
    assert "internal consistency" in fake.requests[0].messages[0]["content"]
    write_reports(paper, settings, out)
    md = (paper / "texclaim_report.md").read_text()
    assert "## Abstract and conclusions consistency" in md
    assert "Contradicted · conclusion" in md
    rep = json.loads((paper / "texclaim_report.json").read_text())
    internal = [f for f in rep["findings"] if f.get("claim_origin") == "internal"]
    assert {f["role"] for f in internal} == {"abstract", "conclusion"}
    assert not [f for f in rep["findings"] if f["kind"] == "claim"]


def test_cli_no_internal(tmp_path):
    from texclaim.cli import app

    paper = _paper(tmp_path)
    r = CliRunner().invoke(app, ["check", str(paper), "--dry-run", "--offline", "--no-internal"])
    assert r.exit_code == 0, r.output
    assert "@self" not in r.output
    r = CliRunner().invoke(app, ["check", str(paper), "--dry-run", "--offline"])
    assert "@self" in r.output


def test_demo_results_are_not_reused_by_a_real_model(tmp_path):
    from texclaim.verifier.demo import DemoVerifier

    paper = _paper(tmp_path)
    settings = load_settings(paper, cli={"model": "demo", "offline": True})
    run_check(paper, settings, DemoVerifier(delay=0), CheckOptions())
    fake = FakeVerifier(_contradicts)
    settings.model = "fake/model"
    settings.internal = InternalSettings(sections=["abstract", "conclusion"])
    out = run_check(paper, settings, fake, CheckOptions())
    assert fake.calls == 2  # both demo verdicts re-verified
    assert not any("another model" in n for n in out.notices)


def test_smallcaps_section_hint():
    from texclaim.reporting.json_report import _smallcaps

    assert _smallcaps("7.2 T EMPORAL AVERAGING") == "7.2 TEMPORAL AVERAGING"
    assert _smallcaps("1 I NTRODUCTION") == "1 INTRODUCTION"
    assert _smallcaps("A B testing") == "A B testing"
