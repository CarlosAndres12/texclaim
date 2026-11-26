"""Opt-in tests against real services: TEXCLAIM_LIVE_TESTS=1 pytest -m live."""

import os

import pytest

from texclaim.sources.arxiv_client import ArxivClient
from texclaim.sources.budget import RunBudget
from texclaim.sources.global_cache import GlobalCache
from texclaim.sources.http import HttpClient
from texclaim.sources.openalex_client import OpenAlexClient

pytestmark = pytest.mark.live


def http() -> HttpClient:
    return HttpClient("texclaim-live-tests", backoff=1.0)


async def test_openalex_doi_lookup(tmp_path):
    cache = GlobalCache(tmp_path)
    client = OpenAlexClient(http(), cache, RunBudget(), os.environ.get("OPENALEX_API_KEY"))
    got = await client.works_by_dois(["10.1038/nature14539"])
    assert "deep learning" in got["10.1038/nature14539"].title.lower()
    cache.close()


async def test_arxiv_download(tmp_path):
    client = ArxivClient(http(), RunBudget())
    data = await client.download("1706.03762")
    assert data is not None and data.startswith(b"%PDF-")


async def test_one_real_llm_call(tmp_path):
    from texclaim.db.source_store import store_doc
    from texclaim.db.state_store import open_db
    from texclaim.models import Unit
    from texclaim.sources.extractor import abstract_doc
    from texclaim.verifier.engine import verify_unit
    from texclaim.verifier.llm_client import LiteLLMVerifier

    model = os.environ.get("TEXCLAIM_MODEL")
    if not model:
        pytest.skip("set TEXCLAIM_MODEL to run the real LLM call")
    from texclaim.config import Settings

    conn = open_db(tmp_path)
    sha = store_doc(conn, abstract_doc("We show that the sky is blue at noon on clear days."))
    unit = Unit(
        "k", "k", "h", "The sky is blue at noon [@k].", "", "sentence", "", "f", 1, "\\cite{k}",
        None, None, ["k"], "The sky is blue at noon", [], "ABSTRACT_ONLY", sha, "en", None, None,
        "abstract",
    )  # fmt: skip
    rec = await verify_unit(unit, conn, LiteLLMVerifier(model), Settings(model=model))
    assert rec.verdict in {"SUPPORTED", "PARTIALLY_SUPPORTED"}


EXPECTED_FLAGS = {
    # example: substrings of statements that must not come out SUPPORTED
    "latex": ["requires a large amount of memory", "more than 5 points"],
    "markdown": ["30,1 BLEU", "a la mitad"],
    "word": ["always converge", "best known result"],
}


@pytest.mark.parametrize("example", sorted(EXPECTED_FLAGS))
def test_examples_end_to_end(tmp_path, example):
    """Real model, real downloads: planted errors in each example are flagged."""
    import json
    import shutil
    from pathlib import Path

    from texclaim.check import CheckOptions, make_verifier, run_check
    from texclaim.config import load_settings
    from texclaim.reporting.write import write_reports

    if not os.environ.get("TEXCLAIM_MODEL"):
        pytest.skip("TEXCLAIM_MODEL not set")
    src = Path(__file__).parents[1] / "examples" / example
    paper = tmp_path / example
    shutil.copytree(src, paper)
    settings = load_settings(paper)
    opts = CheckOptions(openalex_key=os.environ.get("OPENALEX_API_KEY"))
    out = run_check(paper, settings, make_verifier(settings), opts)
    write_reports(paper, settings, out, report_language=opts.report_language)
    rep = json.loads((paper / "texclaim_report.json").read_text())
    assert out.queue_result.errors == 0
    for needle in EXPECTED_FLAGS[example]:
        units = [u for u in rep["units"] if needle in u["claim_text"]]
        assert units, needle
        assert all(u["verdict"] != "SUPPORTED" for u in units), (needle, units[0]["verdict"])
