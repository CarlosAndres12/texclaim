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
