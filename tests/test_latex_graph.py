from texclaim.parser import parse_manuscript
from texclaim.parser.latex_graph import build_graph, section_path
from texclaim.parser.root_finder import find_root


def w(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def graph(paper):
    return build_graph(paper, find_root(paper))


def test_inclusion_order_and_nesting(sample_paper):
    g = graph(sample_paper)
    assert [f.path for f in g.files] == [
        "main.tex",
        "sections/intro.tex",
        "sections/sub/related.tex",
        "sections/sub/extra.tex",
    ]
    assert all(len(f.sha256) == 64 and f.size_bytes > 0 for f in g.files)


def test_missing_include_warns_and_continues(sample_paper):
    g = graph(sample_paper)
    d = [x for x in g.diagnostics if x.code == "UNRESOLVED_INCLUDE"]
    assert len(d) == 1 and d[0].file == "main.tex" and d[0].line == 14
    assert any(f.path.endswith("extra.tex") for f in g.files)  # parsing went on


def test_cycle_is_a_warning(tmp_path):
    w(tmp_path / "main.tex", "\\documentclass{article}\\begin{document}\\input{a}\\end{document}")
    w(tmp_path / "a.tex", "A \\input{b}")
    w(tmp_path / "b.tex", "B \\input{a}")
    g = graph(tmp_path)
    assert [x.code for x in g.diagnostics] == ["INCLUDE_CYCLE"]
    assert len(g.files) == 3


def test_section_carries_across_files(sample_paper):
    g = graph(sample_paper)
    related = next(f for f in g.files if f.path.endswith("related.tex"))
    assert section_path(related, 0) == "Introduction"
    assert section_path(related, len(related.text)) == "Introduction > Related Work"
    extra = next(f for f in g.files if f.path.endswith("extra.tex"))
    assert section_path(extra, 0) == "Methods"


def test_include_variants(tmp_path):
    w(
        tmp_path / "main.tex",
        "\\documentclass{article}\\begin{document}\n\\include{c1}\n\\subfile{d/c2}\n"
        "\\import{d}{c3}\n\\input c4\n\\includeonly{c1}\n\\end{document}",
    )
    for p in ["c1.tex", "d/c2.tex", "d/c3.tex", "c4.tex"]:
        w(tmp_path / p, "x")
    g = graph(tmp_path)
    assert sorted(f.path for f in g.files) == [
        "c1.tex",
        "c4.tex",
        "d/c2.tex",
        "d/c3.tex",
        "main.tex",
    ]
    assert g.includeonly
    assert not g.diagnostics


def test_bib_resources(sample_paper):
    g = graph(sample_paper)
    assert [(b.raw, b.kind) for b in g.bib_resources] == [
        ("references", "bibliography"),
        ("more.bib", "addbibresource"),
    ]


def test_parse_result_has_root(sample_paper):
    assert parse_manuscript(sample_paper).root == "main.tex"
