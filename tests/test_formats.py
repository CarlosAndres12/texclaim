import shutil
import subprocess

import pytest

from texclaim import dotenv, formats
from texclaim.config import ConfigError
from texclaim.formats import refs
from texclaim.parser import parse_manuscript
from texclaim.parser.bib_parser import parse_bib_files

needs_pandoc = pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")

MD = """---
title: Test
abstract: We show that attention works [@vaswani].
bibliography: refs.bib
---

# Introduction

Transformers reach 28.4 BLEU [@vaswani; see @he, p. 3]. @devlin showed pre-training helps.

A footnote claim[^1].

[^1]: Residual nets are deep [@he].

# Conclusion

Our method is the best.
"""

BIB = """@article{vaswani, title={Attention is all you need}, author={Vaswani, Ashish}, year={2017}}
@article{he, title={Deep residual learning}, author={He, Kaiming}, year={2016}}
@article{devlin, title={BERT}, author={Devlin, Jacob}, year={2019}}
"""

NUMERIC = """Intro

ResNets reach 3.57% error [1], and BERT is strong [2-3]. Vaswani et al. (2017) proposed it.

The same holds (He et al., 2016; Devlin et al., 2019).

# References

1. K. He, X. Zhang. Deep residual learning for image recognition.
   CVPR, 2016. doi:10.1109/CVPR.2016.90
2. A. Vaswani et al. "Attention is all you need". NeurIPS 2017. arXiv:1706.03762
3. J. Devlin et al. BERT: Pre-training of deep bidirectional transformers. NAACL 2019.
"""


def _parse(folder):
    prep = formats.prepare(folder, None)
    parsed = parse_manuscript(folder, prep.main)
    formats.remap(prep, parsed)
    bib = parse_bib_files(folder, parsed.root, parsed.bib_resources)
    return prep, parsed, bib


@needs_pandoc
def test_markdown_pandoc_citations(tmp_path):
    (tmp_path / "paper.md").write_text(MD)
    (tmp_path / "refs.bib").write_text(BIB)
    prep, parsed, bib = _parse(tmp_path)
    assert prep.kind == "markdown"
    assert sorted(bib.entries) == ["devlin", "he", "vaswani"]
    by_key = {tuple(k.bib_key for k in c.citations): c for c in parsed.claims}
    assert by_key[("vaswani", "he")].line_start == 9
    assert by_key[("devlin",)].line_start == 9
    assert by_key[("he",)].line_start == 13  # footnote definition line
    assert by_key[("vaswani",)].section_path.startswith("Abstract")
    assert all(c.file_path == "paper.md" for c in parsed.claims)
    assert any(f.path == "paper.md" and f.kind == "markdown" for f in parsed.files)


@needs_pandoc
def test_markdown_numeric_references(tmp_path):
    (tmp_path / "paper.md").write_text(NUMERIC)
    _prep, parsed, bib = _parse(tmp_path)
    assert sorted(bib.entries) == ["ref1", "ref2", "ref3"]
    assert bib.entries["ref1"].doi == "10.1109/cvpr.2016.90"
    assert bib.entries["ref2"].arxiv_id == "1706.03762"
    keys = [[k.bib_key for k in c.citations] for c in parsed.claims]
    assert ["ref1", "ref2", "ref3"] in keys
    assert ["ref2"] in keys  # narrative author-year
    assert ["ref1", "ref3"] in keys  # parenthetical author-year
    lines = sorted(c.line_start for c in parsed.claims)
    assert lines[0] == 3 and lines[-1] == 5


@needs_pandoc
def test_docx_numeric(tmp_path):
    src = tmp_path / "src.md"
    src.write_text(NUMERIC)
    paper = tmp_path / "paper"
    paper.mkdir()
    subprocess.run(["pandoc", str(src), "-o", str(paper / "paper.docx")], check=True)
    prep, parsed, bib = _parse(paper)
    assert prep.kind == "docx" and prep.unit_label == "paragraph"
    assert sorted(bib.entries) == ["ref1", "ref2", "ref3"]
    assert {c.file_path for c in parsed.claims} == {"paper.docx"}
    assert sorted({c.line_start for c in parsed.claims}) == [2, 3]


@needs_pandoc
def test_docx_literal_pandoc_citations(tmp_path):
    src = tmp_path / "src.md"
    src.write_text(MD.replace("bibliography: refs.bib\n", ""))
    paper = tmp_path / "paper"
    paper.mkdir()
    subprocess.run(["pandoc", str(src), "-o", str(paper / "paper.docx")], check=True)
    (paper / "refs.bib").write_text(BIB)
    _prep, parsed, bib = _parse(paper)
    assert sorted(bib.entries) == ["devlin", "he", "vaswani"]
    assert len(parsed.claims) >= 3


def test_detect_prefers_latex(tmp_path):
    (tmp_path / "main.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}")
    (tmp_path / "notes.md").write_text("x")
    assert formats.detect(tmp_path, None)[0] == "latex"


def test_detect_markdown_skips_readme(tmp_path):
    (tmp_path / "README.md").write_text("x")
    (tmp_path / "paper.md").write_text("x")
    kind, doc = formats.detect(tmp_path, None)
    assert kind == "markdown" and doc.name == "paper.md"


def test_detect_ambiguous(tmp_path):
    (tmp_path / "a.md").write_text("x")
    (tmp_path / "b.md").write_text("x")
    with pytest.raises(ConfigError):
        formats.detect(tmp_path, None)


def test_detect_main_extension(tmp_path):
    assert formats.detect(tmp_path, "x.docx")[0] == "docx"
    assert formats.detect(tmp_path, "x.tex")[0] == "latex"


@pytest.mark.parametrize(
    "raw,surname,title",
    [
        ("He, K., Zhang, X. (2016). Deep residual learning for image recognition. CVPR.",
         "He", "Deep residual learning for image recognition"),
        ("Kingma, D. P., & Ba, J. (2015). Adam: A method for stochastic optimization.",
         "Kingma", "Adam: A method for stochastic optimization"),
        ("Srivastava N, Hinton G. Dropout: a simple way to prevent overfitting. JMLR 2014.",
         "Srivastava", "Dropout: a simple way to prevent overfitting"),
        ('A. Vaswani et al. "Attention is all you need". NeurIPS 2017.',
         "Vaswani", "Attention is all you need"),
    ],
)  # fmt: skip
def test_parse_entry(raw, surname, title):
    e = refs.parse_entry(raw, "r1", 1)
    assert e.surnames[0] == surname
    assert e.title == title


def test_numeric_citation_needs_all_numbers():
    entries = [refs.parse_entry("A. B. Title of a work here. 2020.", "ref1", 1)]
    body, n = refs.rewrite_citations("See [1] and [1-2] and [link](x) [1](y).", entries)
    assert body.startswith("See [@ref1] and [1-2]")
    assert n == 1


def test_dotenv_parse_and_precedence(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# c\nexport A=1\nB='two words'\nC=x # note\nEMPTY=\nD=keep\n", encoding="utf-8")
    env = {"D": "real"}
    dotenv.load([f], env)
    assert env == {"A": "1", "B": "two words", "C": "x", "D": "real"}


def _unit(**kw):
    from texclaim.models import Unit

    base = dict(
        unit_key="k", bib_key="b", claim_hash="h", text_norm="S2 [@b].", context_norm="S1 S3",
        unit_kind="sentence", section_path="", file_path="f", line_start=1, cite_command="",
        prenote=None, postnote=None, group_keys=["b"], attributed_span="S2", other_keys=[],
        source_status="FULL_TEXT", text_sha256="x", source_language=None, source_provider=None,
        source_version=None, strategy="full", prev_norm="S1", para_norm="S1 S2 [@b]. S3",
    )  # fmt: skip
    base.update(kw)
    return Unit(**base)


@pytest.mark.parametrize(
    "scope,claim,context",
    [
        ("auto", "sentence: S2 [@b].", "context sentences: S1 S3"),
        ("sentence", "sentence: S2 [@b].", "context sentences: -"),
        ("two", "claim: S1 S2 [@b].", "context sentences: -"),
        ("paragraph", "claim: S1 S2 [@b]. S3", "context sentences: -"),
    ],
)
def test_claim_scope_prompt(scope, claim, context):
    from texclaim.verifier.evidence import Evidence
    from texclaim.verifier.prompts import render_claim

    text = render_claim(
        _unit(claim_scope=scope), Evidence(strategy="full", scope="full_text", blocks=[]), "en"
    )
    assert claim in text and context in text
    assert ("claim scope:" in text) == (scope != "auto")


def test_claim_scope_changes_unit_key():
    from texclaim.planner import unit_key

    kw = dict(
        claim_hash="h", bib_key="b", prenote=None, postnote=None, group_keys=["b"],
        attributed_span="s", source="x", strategy="full",
    )  # fmt: skip
    auto = unit_key(**kw)
    assert auto == unit_key(**kw, claim_scope="auto", scope_text="ignored")
    assert auto != unit_key(**kw, claim_scope="two", scope_text="S1")
    assert unit_key(**kw, claim_scope="two", scope_text="S1") != unit_key(
        **kw, claim_scope="two", scope_text="S1 changed"
    )


def test_extractor_records_prev_and_paragraph(tmp_path):
    from texclaim.parser import parse_manuscript

    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\nFirst point here. Second point \\cite{a}. "
        "Third point.\n\\end{document}\n"
    )
    c = parse_manuscript(tmp_path).claims[0]
    assert c.prev_norm == "First point here."
    assert c.para_norm.startswith("First point here. Second point") and "Third" in c.para_norm
