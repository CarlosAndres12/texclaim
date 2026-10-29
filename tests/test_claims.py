import hashlib

from hypothesis import given
from hypothesis import strategies as st

from texclaim.parser import parse_manuscript
from texclaim.parser.citations import find_citations
from texclaim.parser.claim_extractor import ABBREVIATIONS, split_sentences
from texclaim.parser.masking import mask_comments


def claims_by_text(paper):
    r = parse_manuscript(paper)
    return r, {c.text_norm: c for c in r.claims}


def file_text(paper, rel):
    return (paper / rel).read_text()


def test_exact_spans_for_every_citation(sample_paper):
    r = parse_manuscript(sample_paper)
    assert r.claims
    for c in r.claims:
        text = file_text(sample_paper, c.file_path)
        assert text[c.char_start : c.char_end] == c.raw_latex
        assert text[: c.char_start].count("\n") + 1 == c.line_start
        for cit in c.citations:
            assert text[cit.char_start : cit.char_end].startswith("\\")
            assert cit.char_start >= c.char_start and cit.char_end <= c.char_end
            assert cit.cite_command == text[cit.char_start : cit.char_end]
        assert c.claim_hash == hashlib.sha256(c.text_norm.encode()).hexdigest()


def test_multi_citation_attributed_spans(sample_paper):
    _, by = claims_by_text(sample_paper)
    c = by[
        "Transformers [@vaswani2017] and CNNs [@lecun1998] dominate vision benchmarks "
        "[@dosovitskiy2021]."
    ]
    assert [(x.bib_key, x.attributed_span) for x in c.citations] == [
        ("vaswani2017", "Transformers"),
        ("lecun1998", "and CNNs"),
        ("dosovitskiy2021", c.text_norm),
    ]
    assert c.section_path == "Introduction"
    assert c.line_start == 2


def test_notes_and_command_verbatim(sample_paper):
    _, by = claims_by_text(sample_paper)
    c = by["See also the survey [@smith2020], e.g. by [@doe2024]."]
    first = c.citations[0]
    assert first.cite_command == "\\citep[see][Thm.~2, p.~14]{smith2020}"
    assert (first.prenote, first.postnote) == ("see", "Thm. 2, p. 14")
    assert c.citations[1].prenote is None


def test_group_keys_sorted(sample_paper):
    _, by = claims_by_text(sample_paper)
    c = by["Hybrid models [@vaswani2017; @lecun1998] combine both."]
    assert [x.bib_key for x in c.citations] == ["vaswani2017", "lecun1998"]
    assert all(x.group_keys == ["lecun1998", "vaswani2017"] for x in c.citations)


def test_unit_kinds(sample_paper):
    r, by = claims_by_text(sample_paper)
    kinds = {c.text_norm: c.unit_kind for c in r.claims}
    assert kinds["Results from [@caption2022]."] == "caption"
    assert kinds["This is discussed in [@footnoted2021]."] == "footnote"
    assert kinds["ResNet [@he2016] | 76.1"] == "table_row"
    assert kinds["Neural nets are used widely [@lecun1998]."] == "item"


def test_comments_iffalse_and_nocite_excluded(sample_paper):
    r = parse_manuscript(sample_paper)
    keys = {x.bib_key for c in r.claims for x in c.citations}
    assert "commented2020" not in keys and "hidden2020" not in keys
    assert "nocited2019" not in keys
    assert [k for k, *_ in r.nocite_keys] == ["nocited2019"]


def test_abbreviations_do_not_split(sample_paper):
    _, by = claims_by_text(sample_paper)
    assert "We follow Smith et al. [@smith2020] closely, cf. Fig. 3 in [@lecun1998]." in by
    es = "Un modelo reciente (p. ej. Vaswani et al. [@vaswani2017]) mejora los resultados."
    assert es in by


def test_footnote_is_masked_in_parent(tmp_path):
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\n"
        "Parent text\\footnote{Note \\cite{fn}.} cites \\cite{p}.\n\\end{document}"
    )
    r = parse_manuscript(tmp_path)
    by = {c.text_norm: c for c in r.claims}
    assert set(by) == {"Parent text cites [@p].", "Note [@fn]."}


def test_diagnostics(sample_paper):
    r = parse_manuscript(sample_paper)
    codes = {(d.code, d.severity) for d in r.diagnostics}
    assert ("UNRESOLVED_INCLUDE", "warning") in codes
    assert ("UNKNOWN_CITE_MACRO", "warning") in codes  # \frobcite
    assert ("UNKNOWN_CITE_MACRO", "info") in codes  # \mycite wrapper registered
    wrapped = next(c for c in r.claims if c.text_norm == "[@smith2020] is wrapped.")
    assert wrapped.citations[0].bib_key == "smith2020"


def test_starred_capitalized_and_multicite():
    m = mask_comments(
        "\\Citep*[see]{a} \\parencites(x)(y)[p. 3]{b,c}[q]{d} \\cite{ a , ,b} \\textcite{#1}"
    )
    scan = find_citations(m)
    got = [(o.command, o.keys, o.prenote, o.postnote) for o in scan.occurrences]
    assert got == [
        ("citep", ["a"], None, "see"),
        ("parencites", ["b", "c"], None, "p. 3"),
        ("parencites", ["d"], None, "q"),
        ("cite", ["a", "b"], None, None),
    ]
    assert [d[0] for d in scan.diagnostics] == ["EMPTY_CITE_KEY"]


def test_extra_cite_command():
    scan = find_citations(mask_comments("\\mycite{k}"), {"mycite"})
    assert scan.occurrences[0].keys == ["k"]


def test_spanish_abbreviations_configured():
    assert "p. ej." in ABBREVIATIONS and "et al." in ABBREVIATIONS


def test_sentence_splitter_rules():
    def sp(t):
        return [t[a:b] for a, b in split_sentences(t)]

    assert sp("One. Two? Three! Four.") == ["One.", "Two?", "Three!", "Four."]
    assert sp("See Fig. 3 and Eq. 4. Next.") == ["See Fig. 3 and Eq. 4.", "Next."]
    assert sp("It is 3.5 times. but no") == ["It is 3.5 times. but no"]
    assert sp("Vea Ec. 2 (p. ej. aquí). Luego.") == ["Vea Ec. 2 (p. ej. aquí).", "Luego."]
    assert sp("¿Qué? ¡Nada!") == ["¿Qué?", "¡Nada!"]
    assert sp("Math. \ue000 stays") == ["Math. \ue000 stays"]  # a masked span never starts one


@given(
    st.text(alphabet=st.sampled_from(list("ab \n%\\$.{}[]()verbatimiffalseif\ufb01")), max_size=200)
)
def test_masking_preserves_length_and_newlines(s):
    m = mask_comments(s)
    assert len(m) == len(s)
    assert [i for i, c in enumerate(m) if c == "\n"] == [i for i, c in enumerate(s) if c == "\n"]


def test_masking_cases():
    assert mask_comments("a % c\nb") == "a    \nb"
    assert mask_comments("50\\% off % c") == "50\\% off    "
    assert mask_comments("x \\\\% c") == "x \\\\   "  # \\ then a real comment
    t = "a \\begin{verbatim}%x\\end{verbatim} b \\verb|\\cite{k}| c"
    assert "cite" not in mask_comments(t) and mask_comments(t).endswith(" c")
    assert "hid" not in mask_comments("\\iffalse hid \\ifx a b \\fi \\fi shown")
    assert "shown" in mask_comments("\\iffalse hid \\ifx a b \\fi \\fi shown")


def test_check_dry_run_lists_claims(sample_paper):
    from typer.testing import CliRunner

    from texclaim.cli import app

    r = CliRunner().invoke(app, ["check", str(sample_paper), "--dry-run"])
    assert r.exit_code == 0
    assert "sections/intro.tex:2 [sentence] vaswani2017, lecun1998, dosovitskiy2021" in r.stdout
