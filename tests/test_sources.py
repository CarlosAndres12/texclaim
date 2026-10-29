import json
import shutil

import httpx
import pytest
import respx
from typer.testing import CliRunner

from fixtures.make_pdfs import make_html_as_pdf, make_pdf, paper_pdf
from texclaim import paths
from texclaim.cli import app
from texclaim.config import Settings, load_settings
from texclaim.db.state_store import open_db
from texclaim.parser import parse_manuscript
from texclaim.parser.bib_parser import (
    BibEntry,
    extract_arxiv_id,
    normalize_doi,
    parse_bib_files,
)
from texclaim.sources.arxiv_client import ArxivClient
from texclaim.sources.budget import RunBudget
from texclaim.sources.catalog import resolve_sources, write_catalog
from texclaim.sources.global_cache import GlobalCache, parse_age, parse_size
from texclaim.sources.http import HttpClient, HttpError, OfflineError
from texclaim.sources.locator import Locator
from texclaim.sources.openalex_client import (
    OpenAlexClient,
    accept_title_match,
    parse_work,
    rebuild_abstract,
)

OA = "https://api.openalex.org/works"


def entry(key="k", title="Deep Things", surname="Smith", year="2020", doi=None, arxiv=None):
    return BibEntry(
        key=key, bib_file="r.bib", entry_type="article", title=title,
        authors=[{"first": "A", "last": surname}], year=year, doi=doi, arxiv_id=arxiv,
        pmid=None, local_files=[], entry_hash="h", missing_fields=[],
    )  # fmt: skip


def oa_work(wid="W1", doi="10.1000/a", title="Deep Things", year=2020, surname="Smith", **kw):
    d = {
        "id": f"https://openalex.org/{wid}",
        "doi": f"https://doi.org/{doi}" if doi else None,
        "title": title,
        "publication_year": year,
        "authorships": [{"author": {"display_name": f"Ann {surname}"}}],
        "ids": {},
        "language": "en",
        "is_retracted": False,
        "primary_location": {"landing_page_url": f"https://pub.example/{wid}"},
        "best_oa_location": None,
        "locations": [],
        "has_content": {"pdf": False, "grobid_xml": False},
        "abstract_inverted_index": {"We": [0], "study": [1], "things": [2]},
    }
    d.update(kw)
    return d


def make_http(**kw):
    sleeps: list[float] = []

    async def sleep(s):
        sleeps.append(s)

    return HttpClient("texclaim-test", sleep=sleep, backoff=0.01, **kw), sleeps


@pytest.fixture
def cache(tmp_path):
    c = GlobalCache(tmp_path / "gc")
    yield c
    c.close()


def locator(tmp_path, cache, *, key=None, budget=None, http=None, settings=None, **kw):
    http = http or make_http()[0]
    budget = budget or RunBudget()
    settings = settings or Settings()
    oa = OpenAlexClient(http, cache, budget, key)
    return Locator(
        tmp_path, settings, cache, http=http, openalex=oa, arxiv=ArxivClient(http, budget),
        budget=budget, **kw,
    )  # fmt: skip


# ---- identifiers and bibliography
def test_identifier_normalisation():
    assert normalize_doi("https://doi.org/10.1000/ABC.1.") == "10.1000/abc.1"
    assert normalize_doi("doi:10.1000/x(1)") == "10.1000/x(1)"
    assert normalize_doi("not a doi") is None
    assert extract_arxiv_id("arXiv:1706.03762v5") == "1706.03762"
    assert extract_arxiv_id("see https://arxiv.org/abs/hep-th/9901001") == "hep-th/9901001"
    assert extract_arxiv_id("Journal of Things 12") is None


def test_bib_parsing_fixture(sample_paper):
    parsed = parse_manuscript(sample_paper)
    db = parse_bib_files(sample_paper, parsed.root, parsed.bib_resources)
    assert db.entries["smith2020"].doi == "10.1000/things.2020.1"
    assert db.entries["smith2020"].bib_file == "references.bib"  # first definition wins
    assert db.duplicates == {"smith2020": ["references.bib", "more.bib"]}
    v = db.entries["vaswani2017"]
    assert (v.doi, v.arxiv_id, v.lookup_doi) == (None, "1706.03762", "10.48550/arxiv.1706.03762")
    assert db.entries["lecun1998"].lookup_doi is None
    assert db.entries["lecun1998"].first_surname == "LeCun"
    assert {f.path for f in db.files} == {"references.bib", "more.bib"}


def test_bib_file_field_malformed_and_missing(tmp_path):
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\\cite{a}\\bibliography{r,nope}\\end{document}"
    )
    (tmp_path / "r.bib").write_text(
        "@article{a, title={T}, author={X, Y}, year={2000}, file={:papers/a.pdf:PDF;:b.txt:TXT}}\n"
        "@article{broken, title = {unterminated\n"
    )
    parsed = parse_manuscript(tmp_path)
    db = parse_bib_files(tmp_path, parsed.root, parsed.bib_resources)
    assert db.entries["a"].local_files == ["papers/a.pdf"]
    assert [d.code for d in db.diagnostics] == ["MISSING_BIB_FILE"]


# ---- OpenAlex
def test_abstract_rebuild_and_parse():
    assert rebuild_abstract({"b": [1], "a": [0]}) == "a b"
    w = parse_work(
        oa_work(
            locations=[{"landing_page_url": "https://arxiv.org/abs/1706.03762v3", "pdf_url": None}]
        )
    )
    assert (w.openalex_id, w.doi, w.arxiv_id, w.surnames) == (
        "W1",
        "10.1000/a",
        "1706.03762",
        ["Smith"],
    )


def test_title_acceptance_rules():
    e = entry()
    assert accept_title_match(e, parse_work(oa_work()))
    assert not accept_title_match(e, parse_work(oa_work(year=2023)))
    assert not accept_title_match(e, parse_work(oa_work(surname="Jones")))
    assert not accept_title_match(e, parse_work(oa_work(title="Unrelated Topic Entirely")))
    assert not accept_title_match(entry(year=None), parse_work(oa_work()))


@respx.mock
async def test_batch_doi_lookup_and_title_search(cache):
    seen = []

    def handler(request):
        seen.append(request)
        p = request.url.params
        if "search.title" in p:
            hit = oa_work("W9", doi=None, title="Unrelated Paper", surname="Zed")
            good = oa_work("W3", doi=None, title="Searchable Title", surname="Lee", year=2019)
            return httpx.Response(200, json={"results": [hit, good]})
        assert p["filter"] == "doi:10.1000/a|10.1000/b"
        return httpx.Response(
            200, json={"results": [oa_work("W1", "10.1000/a"), oa_work("W2", "10.1000/b")]}
        )

    respx.get(OA).mock(side_effect=handler)
    http, _ = make_http()
    client = OpenAlexClient(http, cache, RunBudget(), "secret-key")
    entries = [
        entry("a", doi="10.1000/a"),
        entry("b", doi="10.1000/b"),
        entry("c", title="Searchable Title", surname="Lee", year="2019"),
    ]
    got = await client.resolve_all(entries)
    assert [got[k].openalex_id for k in "abc"] == ["W1", "W2", "W3"]
    assert len(seen) == 2  # one batch call and one title search
    assert seen[0].headers["authorization"] == "Bearer secret-key"
    assert "secret-key" not in str(seen[0].url)
    assert seen[1].url.params["filter"] == "publication_year:2018-2020"
    # a second resolution is served from the global cache
    again = await client.works_by_dois(["10.1000/a", "10.1000/b"])
    assert set(again) == {"10.1000/a", "10.1000/b"} and len(seen) == 2


@respx.mock
async def test_inactive_key_falls_back_to_keyless(cache):
    calls = []

    def handler(request):
        calls.append(request.headers.get("authorization"))
        if request.headers.get("authorization"):
            return httpx.Response(403, json={"error": "key_not_activated"})
        return httpx.Response(200, json={"results": [oa_work()]})

    respx.get(OA).mock(side_effect=handler)
    http, _ = make_http()
    client = OpenAlexClient(http, cache, RunBudget(), "k")
    assert (await client.works_by_dois(["10.1000/a"]))["10.1000/a"].openalex_id == "W1"
    assert calls == ["Bearer k", None]


# ---- HTTP layer
@respx.mock
async def test_retry_after_is_honored():
    route = respx.get("https://x.example/f").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, content=b"ok"),
        ]
    )
    http, sleeps = make_http()
    r = await http.get("https://x.example/f")
    assert r.status == 200 and route.call_count == 2
    assert max(sleeps) >= 7


@respx.mock
async def test_gives_up_after_retries_and_size_cap():
    respx.get("https://x.example/e").mock(return_value=httpx.Response(503))
    http, _ = make_http(retries=3)
    assert (await http.get("https://x.example/e")).status == 503
    respx.get("https://x.example/net").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(HttpError):
        await http.get("https://x.example/net")
    respx.get("https://x.example/big").mock(return_value=httpx.Response(200, content=b"x" * 500))
    small, _ = make_http(max_bytes=100)
    with pytest.raises(HttpError, match="size"):
        await small.get("https://x.example/big")


async def test_offline_client_refuses():
    http, _ = make_http(offline=True)
    with pytest.raises(OfflineError):
        await http.get("https://x.example")
    assert http.request_count == 0


# ---- global cache
def test_cache_blobs_negative_and_prune(cache):
    sha = cache.put_blob(b"%PDF-1.4 data", "application/pdf", "http://u")
    assert cache.put_blob(b"%PDF-1.4 data") == sha  # same bytes, same blob
    p = cache.get_blob(sha)
    assert p and p.parts[-3:-1] == (sha[:2], sha[2:4])
    cache.set_identifier("doi", "10.1000/A", sha, "arxiv", "submittedVersion")
    assert cache.lookup_identifier("doi", "10.1000/a")["provider"] == "arxiv"
    assert not cache.is_negative("doi", "10.1000/z", "arxiv")
    cache.add_negative("doi", "10.1000/z", "arxiv", "none")
    assert cache.is_negative("doi", "10.1000/z", "arxiv")
    cache.db.execute("UPDATE negative SET checked_at='2000-01-01T00:00:00+00:00'")
    assert not cache.is_negative("doi", "10.1000/z", "arxiv")  # 7-day TTL
    assert cache.info()["blobs"] == 1
    assert cache.prune(max_bytes=1) == 1 and cache.get_blob(sha) is None
    assert parse_age("180d").days == 180 and parse_size("5GB") == 5_000_000_000


# ---- locator cascade
def pdf_for(e: BibEntry, **kw) -> bytes:
    return paper_pdf(e.title, f"Ann {e.first_surname}", ["Body text of the paper."], **kw)


@respx.mock
async def test_closed_access_falls_back_to_abstract(tmp_path, cache):
    w = parse_work(oa_work())
    res = await locator(tmp_path, cache).locate(entry(doi="10.1000/a"), w)
    assert (res.status, res.provider, res.abstract) == (
        "ABSTRACT_ONLY",
        "abstract",
        "We study things",
    )
    assert [t["provider"] for t in res.trail][:2] == ["local", "cache"]


@respx.mock
async def test_html_saved_as_pdf_is_rejected(tmp_path, cache):
    w = parse_work(
        oa_work(
            best_oa_location={"pdf_url": "https://pub.example/x.pdf", "version": "publishedVersion"}
        )
    )
    respx.get("https://pub.example/x.pdf").mock(
        return_value=httpx.Response(200, content=make_html_as_pdf())
    )
    res = await locator(tmp_path, cache).locate(entry(), w)
    assert res.status == "ABSTRACT_ONLY"
    assert any(t["outcome"] == "not_a_pdf" for t in res.trail)
    assert cache.info()["blobs"] == 0


@respx.mock
async def test_identity_mismatch_is_kept_but_not_used(tmp_path, cache):
    other = paper_pdf("A Completely Different Paper About Birds", "Zed Zimmer", ["Birds sing."])
    w = parse_work(
        oa_work(
            abstract_inverted_index=None, best_oa_location={"pdf_url": "https://pub.example/x.pdf"}
        )
    )
    respx.get("https://pub.example/x.pdf").mock(return_value=httpx.Response(200, content=other))
    res = await locator(tmp_path, cache).locate(entry(), w)
    assert res.status == "SOURCE_IDENTITY_MISMATCH" and res.blob_sha256 is None
    sha = res.failures[0]["sha256"]
    assert cache.get_blob(sha) is not None  # kept for inspection
    assert cache.lookup_identifier("doi", "10.1000/a") is None  # never offered as a source


@respx.mock
async def test_oa_location_download_then_cache_hit(tmp_path, cache):
    e = entry(doi="10.1000/a")
    w = parse_work(
        oa_work(
            best_oa_location={"pdf_url": "https://pub.example/x.pdf", "version": "acceptedVersion"}
        )
    )
    route = respx.get("https://pub.example/x.pdf").mock(
        return_value=httpx.Response(200, content=pdf_for(e))
    )
    res = await locator(tmp_path, cache).locate(e, w)
    assert (res.status, res.provider, res.version) == (
        "FULL_TEXT",
        "oa_locations",
        "acceptedVersion",
    )
    again = await locator(tmp_path, cache).locate(e, w)
    assert (again.provider, again.blob_sha256, route.call_count) == ("cache", res.blob_sha256, 1)
    assert again.version == "acceptedVersion"


@respx.mock
async def test_paid_download_cap(tmp_path, cache):
    works = {}
    entries = []
    for i in range(3):
        e = entry(f"k{i}", title=f"Paper Number {i}", doi=f"10.1000/{i}")
        entries.append(e)
        works[e.key] = parse_work(
            oa_work(f"W{i}", f"10.1000/{i}", e.title, has_content={"pdf": True})
        )
    bodies = {f"W{i}": pdf_for(entries[i]) for i in range(3)}
    route = respx.get(url__regex=r"https://content\.openalex\.org/works/(?P<w>W\d)\.pdf").mock(
        side_effect=lambda req, **kw: httpx.Response(
            200, content=bodies[req.url.path.split("/")[-1][:-4]]
        )
    )
    budget = RunBudget(openalex_max_usd=0.02)
    loc = locator(tmp_path, cache, key="key", budget=budget)
    out = [await loc.locate(e, works[e.key]) for e in entries]
    assert [r.provider for r in out] == ["openalex_content", "openalex_content", "abstract"]
    assert route.call_count == 2 and budget.openalex_spent == pytest.approx(0.02)
    assert route.calls[0].request.headers["authorization"] == "Bearer key"


@respx.mock
async def test_local_pdf_by_key_by_doi_and_other_name(tmp_path, cache):
    (tmp_path / "papers").mkdir()
    e = entry("smith", doi="10.1000/a")
    (tmp_path / "papers" / "smith.pdf").write_bytes(pdf_for(e, pad=False))
    r = await locator(tmp_path, cache).locate(e, None)
    assert (r.status, r.provider) == ("FULL_TEXT", "local")
    (tmp_path / "papers" / "smith.pdf").unlink()
    (tmp_path / "papers" / "Zotero Export 1.pdf").write_bytes(pdf_for(e, pad=False))
    cache2 = GlobalCache(tmp_path / "gc2")
    r2 = await locator(tmp_path, cache2).locate(e, None)
    assert (r2.status, r2.provider) == ("FULL_TEXT", "local")
    cache2.close()


@respx.mock
async def test_arxiv_limits_and_block(tmp_path, cache):
    http, sleeps = make_http()
    budget = RunBudget(arxiv_max_downloads=5)
    e1, e2 = (
        entry("a", title="Alpha Paper", arxiv="1706.00001"),
        entry("b", title="Beta", arxiv="1706.00002"),
    )
    route = respx.get("https://arxiv.org/pdf/1706.00001").mock(
        return_value=httpx.Response(200, content=pdf_for(e1))
    )
    blocked = respx.get("https://arxiv.org/pdf/1706.00002").mock(return_value=httpx.Response(429))
    loc = locator(tmp_path, cache, http=http, budget=budget)
    r1 = await loc.locate(e1, None)
    assert (r1.provider, r1.version) == ("arxiv", "submittedVersion")
    r2 = await loc.locate(e2, None)
    assert r2.status == "NO_SOURCE" and budget.arxiv_blocked
    e3 = entry("c", title="Gamma", arxiv="1706.00003")
    r3 = await loc.locate(e3, None)
    assert any(t["detail"] == "limit or blocked" for t in r3.trail)
    assert route.call_count == 1 and blocked.call_count >= 1
    assert any(s >= 2.9 for s in sleeps) or http.request_count <= 2


@respx.mock
async def test_offline_makes_zero_requests(tmp_path, cache):
    stray = respx.route().mock(return_value=httpx.Response(200))
    e = entry(doi="10.1000/a")
    cache.put_work(oa_work())
    http, _ = make_http(offline=True)
    settings = Settings(offline=True)
    loc = Locator(tmp_path, settings, cache, http=http)
    out = await loc.locate_all([e])
    assert out["k"].status == "ABSTRACT_ONLY"  # cached OpenAlex work still gives an abstract
    assert stray.call_count == 0 and http.request_count == 0


# ---- whole-paper behaviour
@respx.mock
async def test_two_papers_one_doi_one_download(tmp_path, sample_paper):
    paper2 = tmp_path / "paper2"
    shutil.copytree(sample_paper, paper2)
    cache = GlobalCache(tmp_path / "shared-cache")
    pdf = make_pdf(["A Study of Things\nJane Smith\nBody."])
    work = oa_work("W5", "10.1000/things.2020.1", "A Study of Things", 2020, "Smith",
                   best_oa_location={"pdf_url": "https://pub.example/s.pdf"})  # fmt: skip
    respx.get(OA).mock(return_value=httpx.Response(200, json={"results": [work]}))
    respx.get(url__regex=r"https://api\.openalex\.org/works/.+").mock(
        return_value=httpx.Response(404)
    )
    respx.get(url__regex=r"https://arxiv\.org/.+").mock(return_value=httpx.Response(404))
    dl = respx.get("https://pub.example/s.pdf").mock(return_value=httpx.Response(200, content=pdf))
    settings = Settings()
    for paper in (sample_paper, paper2):
        parsed = parse_manuscript(paper)
        bibdb = parse_bib_files(paper, parsed.root, parsed.bib_resources)
        http, _ = make_http()
        results, _ = await resolve_sources(paper, parsed, bibdb, settings, cache, http=http)
        conn = open_db(paper)
        write_catalog(conn, parsed, bibdb, results)
        rows = {r["bib_key"]: r for r in conn.execute("SELECT * FROM references_catalog")}
        assert rows["smith2020"]["source_status"] == "FULL_TEXT"
        assert rows["doe2024"]["source_status"] == "MISSING_BIB_ENTRY"
        assert json.loads(rows["smith2020"]["lookup_trail_json"])["trail"]
        conn.close()
    assert dl.call_count == 1  # second paper reuses the shared cache
    cache.close()


def test_fetch_command_offline_prints_checklist(sample_paper):
    r = CliRunner().invoke(app, ["fetch", str(sample_paper), "--offline"])
    assert r.exit_code == 0, r.output
    assert "0 of" in r.stdout
    assert "drop a PDF at: papers/smith2020.pdf" in r.stdout
    assert "https://doi.org/10.1000/things.2020.1" in r.stdout
    assert paths.paper_db_path(sample_paper).exists()


def test_fetch_creates_snapshot(sample_paper):
    CliRunner().invoke(app, ["fetch", str(sample_paper), "--offline"])
    conn = open_db(sample_paper)
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] > 5
    assert conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0] > 8
    assert conn.execute("SELECT COUNT(*) FROM source_files WHERE kind='bib'").fetchone()[0] == 2
    # a second run replaces the snapshot rather than appending to it
    n = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    CliRunner().invoke(app, ["fetch", str(sample_paper), "--offline"])
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == n


def test_settings_default_order():
    assert load_settings(None).sources.order[0] == "local"
