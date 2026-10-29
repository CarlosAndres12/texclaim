import asyncio

import pytest
from typer.testing import CliRunner

import texclaim.planner
from fixtures.make_pdfs import paper_pdf
from texclaim.check import CheckOptions, run_check
from texclaim.cli import app
from texclaim.config import ConfigError, Settings
from texclaim.db.state_store import open_db
from texclaim.models import VerifierOutput
from texclaim.planner import is_deterministic
from texclaim.sources.global_cache import GlobalCache
from texclaim.verifier.fake import FakeVerifier, default_output

TITLES = {
    "smith2020": ("A Study of Things", "Jane Smith"),
    "vaswani2017": ("Attention Is All You Need", "Ashish Vaswani"),
    "lecun1998": ("Gradient-Based Learning Applied to Document Recognition", "Yann LeCun"),
    "dosovitskiy2021": ("An Image is Worth 16x16 Words", "Alexey Dosovitskiy"),
    "he2016": ("Deep Residual Learning for Image Recognition", "Kaiming He"),
    "footnoted2021": ("Footnoted", "B A"),
    "caption2022": ("Captioned", "D C"),
}
BODY = "This study reports careful measurements of widgets under many conditions. " * 6


def add_pdf(paper, key):
    title, author = TITLES[key]
    d = paper / "papers"
    d.mkdir(exist_ok=True)
    (d / f"{key}.pdf").write_bytes(paper_pdf(title, author, [BODY, BODY]))


@pytest.fixture
def paper(sample_paper):
    for k in TITLES:
        add_pdf(sample_paper, k)
    return sample_paper


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "gc"


def check(paper, cache_dir, verifier, *, model=None, **kw):
    stop = kw.pop("stop", None)
    opts = CheckOptions(cache_dir=cache_dir, concurrency=kw.pop("concurrency", 4), **kw)
    settings = Settings(offline=True, model=model)
    return run_check(paper, settings, verifier, opts, stop=stop)


class Fake(FakeVerifier):
    def __init__(self, model="fake/a", **kw):
        super().__init__(**kw)
        self.model = model


def llm_units(paper, cache_dir):
    conn = open_db(paper)
    from texclaim.planner import load_units

    units = [u for u in load_units(conn, Settings(offline=True)) if not is_deterministic(u)]
    conn.close()
    return units


def n_results(paper):
    conn = open_db(paper)
    n = conn.execute("SELECT COUNT(*) FROM verification_results").fetchone()[0]
    conn.close()
    return n


def edit(paper, rel, old, new):
    p = paper / rel
    text = p.read_text()
    assert old in text
    p.write_text(text.replace(old, new, 1))


def test_first_run_then_zero_calls(paper, cache_dir):
    v = Fake()
    first = check(paper, cache_dir, v)
    n = len(llm_units(paper, cache_dir))
    assert n >= 10 and v.calls == n and first.status == "completed"
    assert first.queue_result.verified == n
    v2 = Fake()
    second = check(paper, cache_dir, v2)
    assert v2.calls == 0 and second.queue == [] and second.reused == len(second.units)
    # deterministic results were written once and not repeated
    conn = open_db(paper)
    dup = conn.execute(
        "SELECT unit_key FROM verification_results GROUP BY unit_key HAVING COUNT(*) > 1"
    ).fetchall()
    assert dup == []
    kinds = {r[0] for r in conn.execute("SELECT DISTINCT origin FROM verification_results")}
    assert kinds == {"llm", "deterministic"}


def test_sentence_edit_reverifies_exactly_its_units(paper, cache_dir):
    check(paper, cache_dir, Fake())
    edit(paper, "sections/intro.tex", "Neural nets are used widely", "Neural nets are used rarely")
    v = Fake()
    check(paper, cache_dir, v)
    assert v.calls == 1 and v.requests[0].unit.bib_key == "lecun1998"
    assert "rarely" in v.requests[0].unit.text_norm


def test_citation_added_requeues_all_units_of_the_sentence(paper, cache_dir):
    check(paper, cache_dir, Fake())
    edit(
        paper, "sections/intro.tex", "widely \\cite{lecun1998}", "widely \\cite{lecun1998, he2016}"
    )
    v = Fake()
    check(paper, cache_dir, v)
    assert sorted(r.unit.bib_key for r in v.requests) == ["he2016", "lecun1998"]


def test_postnote_change_requeues_that_unit(paper, cache_dir):
    check(paper, cache_dir, Fake())
    edit(paper, "sections/intro.tex", "Thm.~2, p.~14", "Thm.~2, p.~15")
    v = Fake()
    check(paper, cache_dir, v)
    assert v.calls == 1 and v.requests[0].unit.postnote == "Thm. 2, p. 15"


def test_cosmetic_edits_make_no_calls(paper, cache_dir):
    check(paper, cache_dir, Fake())
    edit(
        paper, "sections/intro.tex", "Transformers \\cite", "% a new comment\nTransformers   \\cite"
    )
    edit(paper, "main.tex", "We follow Smith et al.~", "We follow\n  Smith et al.~")
    v = Fake()
    check(paper, cache_dir, v)
    assert v.calls == 0


def test_neighbouring_sentence_edit_makes_no_calls(paper, cache_dir):
    check(paper, cache_dir, Fake())
    edit(paper, "sections/sub/related.tex", "Otra frase sin cita.", "Una frase distinta sin cita.")
    v = Fake()
    check(paper, cache_dir, v)
    assert v.calls == 0


def test_moving_a_paragraph_to_another_file_makes_no_calls(paper, cache_dir):
    check(paper, cache_dir, Fake())
    extra = paper / "sections/sub/extra.tex"
    sentence = extra.read_text()
    extra.write_text("")
    edit(paper, "main.tex", "\\bibliographystyle{plain}", sentence + "\n\\bibliographystyle{plain}")
    v = Fake()
    check(paper, cache_dir, v)
    assert v.calls == 0


def test_interrupt_then_rerun_makes_exactly_the_remaining_calls(paper, cache_dir):
    check(paper, cache_dir, Fake(), dry_run=True)  # builds the snapshot
    n = len(llm_units(paper, cache_dir))
    stop = asyncio.Event()
    v = Fake(delay=0.01)
    orig = v.verify

    async def verify(req):
        if v.calls == 2:
            stop.set()
        return await orig(req)

    v.verify = verify
    first = check(paper, cache_dir, v, stop=stop, concurrency=4)
    done = first.queue_result.verified
    assert first.status == "interrupted" and 2 <= done < n
    assert first.incomplete and first.queue_result.skipped == n - done
    v2 = Fake()
    second = check(paper, cache_dir, v2)
    assert v2.calls == n - done and second.status == "completed"
    conn = open_db(paper)
    dup = conn.execute(
        "SELECT unit_key FROM verification_results GROUP BY unit_key HAVING COUNT(*) > 1"
    ).fetchall()
    assert dup == []


def test_force_and_resume(paper, cache_dir):
    check(paper, cache_dir, Fake())
    n = len(llm_units(paper, cache_dir))
    v = Fake()
    forced = check(paper, cache_dir, v, force=True)
    assert v.calls == n and forced.status == "completed"

    stop = asyncio.Event()
    v = Fake(delay=0.01)
    orig = v.verify

    async def verify(req):
        if v.calls == 2:
            stop.set()
        return await orig(req)

    v.verify = verify
    part = check(paper, cache_dir, v, force=True, stop=stop)
    done = part.queue_result.verified
    assert part.status == "interrupted" and done < n
    # a plain run would see every unit as already verified; --resume finishes the force
    v2 = Fake()
    assert check(paper, cache_dir, v2).queue == []
    res = check(paper, cache_dir, v2, resume=True)
    assert v2.calls == n - done and res.status == "completed"
    assert check(paper, cache_dir, Fake()).queue == []


def test_resume_without_interrupted_run_is_an_error(paper, cache_dir):
    check(paper, cache_dir, Fake())
    with pytest.raises(ConfigError, match="resume"):
        check(paper, cache_dir, Fake(), resume=True)


def test_budget_exhausted_then_resume(paper, cache_dir):
    v = Fake(cost=0.4)
    first = check(paper, cache_dir, v, max_cost=1.0, concurrency=1)
    n = len(llm_units(paper, cache_dir))
    assert (first.status, v.calls) == ("budget_exhausted", 2) and first.incomplete
    v2 = Fake()
    second = check(paper, cache_dir, v2, resume=True)
    assert v2.calls == n - 2 and second.status == "completed"


def test_dropping_a_pdf_requeues_only_that_keys_units(paper, cache_dir):
    (paper / "papers" / "dosovitskiy2021.pdf").unlink()
    cache = GlobalCache(cache_dir)
    cache.put_work(
        {
            "id": "https://openalex.org/W9",
            "doi": "https://doi.org/10.48550/arxiv.2010.11929",
            "title": "An Image is Worth 16x16 Words",
            "publication_year": 2021,
            "abstract_inverted_index": {"We": [0], "classify": [1], "images": [2]},
        }
    )
    cache.close()
    first = Fake()
    out = check(paper, cache_dir, first)
    unit = next(u for u in out.units if u.bib_key == "dosovitskiy2021")
    assert unit.strategy == "abstract"
    add_pdf(paper, "dosovitskiy2021")
    v = Fake()
    check(paper, cache_dir, v)
    assert [r.unit.bib_key for r in v.requests] == ["dosovitskiy2021"]
    assert v.requests[0].evidence.scope == "full_text"


def test_no_source_unit_requeues_when_pdf_appears(paper, cache_dir):
    (paper / "papers" / "he2016.pdf").unlink()
    check(paper, cache_dir, Fake())
    add_pdf(paper, "he2016")
    v = Fake()
    check(paper, cache_dir, v)
    assert {r.unit.bib_key for r in v.requests} == {"he2016"}


def test_model_change_notice_and_stale_recheck(paper, cache_dir):
    check(paper, cache_dir, Fake("fake/a"))
    n = len(llm_units(paper, cache_dir))
    v = Fake("fake/b")
    out = check(paper, cache_dir, v)
    assert v.calls == 0
    assert any("another model" in x and "--recheck stale-model" in x for x in out.notices)
    v = Fake("fake/b")
    out = check(paper, cache_dir, v, recheck="stale-model")
    assert v.calls == n
    v = Fake("fake/b")
    assert check(paper, cache_dir, v, recheck="stale-model").queue == []


def test_recheck_flagged_only(paper, cache_dir):
    def responder(req):
        o = default_output(req)
        if req.unit.bib_key == "he2016":
            return VerifierOutput(
                **{**o.model_dump(), "verdict": "CONTRADICTED", "what_is_wrong": "x",
                   "what_source_says": "y"}
            )  # fmt: skip
        return o

    check(paper, cache_dir, Fake(responder=responder))
    v = Fake(responder=responder)
    check(paper, cache_dir, v, recheck="flagged")
    assert {r.unit.bib_key for r in v.requests} == {"he2016"}


def test_prompt_major_bump_requeues_everything(paper, cache_dir, monkeypatch):
    check(paper, cache_dir, Fake())
    n = len(llm_units(paper, cache_dir))
    monkeypatch.setattr(texclaim.planner, "PROMPT_MAJOR", "2")
    v = Fake()
    check(paper, cache_dir, v)
    assert v.calls == n


def test_only_file_and_only_key_scope_force(paper, cache_dir):
    check(paper, cache_dir, Fake())
    v = Fake()
    check(paper, cache_dir, v, force=True, only_keys=["he2016"])
    assert {r.unit.bib_key for r in v.requests} == {"he2016"}
    v = Fake()
    check(paper, cache_dir, v, force=True, only_files=["sections/sub/extra.tex"])
    assert [r.unit.file_path for r in v.requests] == ["sections/sub/extra.tex"]


def test_dry_run_makes_no_calls_and_stores_nothing(paper, cache_dir):
    v = Fake()
    out = check(paper, cache_dir, v, dry_run=True)
    assert v.calls == 0 and out.status == "dry-run" and len(out.queue) >= 10
    assert n_results(paper) == 0


def test_provider_error_gives_exit_code_3(paper, cache_dir, monkeypatch):
    import texclaim.check as chk

    monkeypatch.setattr(chk, "make_verifier", lambda s, k=None: Fake(fail_keys={"he2016"}))
    r = CliRunner().invoke(
        app,
        ["check", str(paper), "--offline", "--model", "fake/a", "--cache-dir", str(cache_dir)],
    )
    assert r.exit_code == 3, r.output
    conn = open_db(paper)
    assert conn.execute("SELECT COUNT(*) FROM run_errors").fetchone()[0] >= 1
    # the failed unit is retried next time and nothing else is
    monkeypatch.setattr(chk, "make_verifier", lambda s, k=None: Fake())
    r = CliRunner().invoke(
        app,
        ["check", str(paper), "--offline", "--model", "fake/a", "--cache-dir", str(cache_dir)],
    )
    # only the one failed unit was queued; exit 1 is the fixture's missing .bib entry (fail-on)
    assert "1 of 1 queued units verified" in r.output and r.exit_code == 1, r.output


def test_check_without_model_exits_2(paper, cache_dir):
    r = CliRunner().invoke(app, ["check", str(paper), "--offline", "--cache-dir", str(cache_dir)])
    assert r.exit_code == 2 and "TEXCLAIM_MODEL" in r.output


async def test_first_sigint_sets_stop_flag():
    import os
    import signal

    from texclaim.check import install_signal_handlers

    stop = asyncio.Event()
    undo = install_signal_handlers(asyncio.get_running_loop(), stop)
    try:
        os.kill(os.getpid(), signal.SIGINT)
        await asyncio.sleep(0.05)
        assert stop.is_set()
    finally:
        undo()
