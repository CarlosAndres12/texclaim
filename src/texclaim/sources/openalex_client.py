"""OpenAlex: resolving cited works and fetching full text (PLAN §7.2, §7.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote

from rapidfuzz import fuzz

from texclaim.parser.bib_parser import BibEntry, extract_arxiv_id, normalize_doi
from texclaim.sources.budget import RunBudget
from texclaim.sources.global_cache import GlobalCache
from texclaim.sources.http import HttpClient, HttpResult
from texclaim.sources.identity import norm

API = "https://api.openalex.org"
CONTENT = "https://content.openalex.org"
SELECT = (
    "id,doi,title,publication_year,authorships,ids,type,language,is_retracted,primary_location,"
    "best_oa_location,locations,open_access,has_content,content_urls,abstract_inverted_index"
)


@dataclass
class OaLocation:
    pdf_url: str | None
    landing_page_url: str | None
    version: str | None


@dataclass
class OpenAlexWork:
    openalex_id: str  # short form, W123
    doi: str | None
    title: str | None
    year: int | None
    surnames: list[str]
    language: str | None
    is_retracted: bool
    pmid: str | None
    arxiv_id: str | None
    has_pdf_content: bool
    has_grobid: bool
    locations: list[OaLocation] = field(default_factory=list)  # best OA location first
    abstract: str | None = None
    landing_page: str | None = None
    raw: dict = field(default_factory=dict, repr=False)


def rebuild_abstract(inv: dict | None) -> str | None:
    if not inv:
        return None
    slots: dict[int, str] = {}
    for word, positions in inv.items():
        for p in positions:
            slots[p] = word
    return " ".join(slots[i] for i in sorted(slots)) or None


def _loc(d: dict | None) -> OaLocation | None:
    if not d:
        return None
    return OaLocation(d.get("pdf_url"), d.get("landing_page_url"), d.get("version"))


def parse_work(d: dict) -> OpenAlexWork:
    locs: list[OaLocation] = []
    for cand in [d.get("best_oa_location"), *(d.get("locations") or [])]:
        loc = _loc(cand)
        if loc and loc.pdf_url and all(loc.pdf_url != x.pdf_url for x in locs):
            locs.append(loc)
    arxiv = None
    for cand in [d.get("primary_location"), *(d.get("locations") or [])]:
        for u in ((cand or {}).get("landing_page_url"), (cand or {}).get("pdf_url")):
            arxiv = arxiv or extract_arxiv_id(u)
    doi = normalize_doi(d.get("doi"))
    if doi and doi.startswith("10.48550/arxiv."):
        arxiv = arxiv or doi.split("arxiv.", 1)[1]
    ids = d.get("ids") or {}
    pmid = (ids.get("pmid") or "").rsplit("/", 1)[-1] or None
    hc = d.get("has_content") or {}
    surnames = []
    for a in d.get("authorships") or []:
        name = ((a.get("author") or {}).get("display_name") or "").strip()
        if name:
            surnames.append(name.split()[-1])
    prim = d.get("primary_location") or {}
    return OpenAlexWork(
        openalex_id=str(d.get("id", "")).rsplit("/", 1)[-1],
        doi=doi,
        title=d.get("title") or d.get("display_name"),
        year=d.get("publication_year"),
        surnames=surnames,
        language=d.get("language"),
        is_retracted=bool(d.get("is_retracted")),
        pmid=pmid,
        arxiv_id=arxiv,
        has_pdf_content=bool(hc.get("pdf")),
        has_grobid=bool(hc.get("grobid_xml")),
        locations=locs,
        abstract=rebuild_abstract(d.get("abstract_inverted_index")),
        landing_page=prim.get("landing_page_url") or d.get("doi"),
        raw=d,
    )


def accept_title_match(entry: BibEntry, cand: OpenAlexWork) -> bool:
    """Strict acceptance of a title-search hit: title, an author surname and the year agree."""
    if not entry.title or not cand.title or not entry.authors or not entry.year:
        return False
    if fuzz.token_set_ratio(norm(entry.title), norm(cand.title)) < 90:
        return False
    mine = {norm(a["last"]).split()[-1] for a in entry.authors if norm(a["last"])}
    theirs = {norm(s) for s in cand.surnames}
    if not mine & theirs:
        return False
    try:
        return cand.year is not None and abs(int(entry.year) - int(cand.year)) <= 1
    except ValueError:
        return False


class OpenAlexClient:
    def __init__(
        self,
        http: HttpClient,
        cache: GlobalCache,
        budget: RunBudget,
        api_key: str | None = None,
    ) -> None:
        self.http, self.cache, self.budget, self.api_key = http, cache, budget, api_key
        rate = 30.0 if api_key else 10.0
        http.set_interval("api.openalex.org", 1.0 / rate)
        http.set_interval("content.openalex.org", 1.0 / rate)
        self.key_inactive = False

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _note(self, r: HttpResult) -> None:
        rem = r.headers.get("x-ratelimit-remaining-usd") or r.headers.get(
            "X-RateLimit-Remaining-USD"
        )
        try:
            if rem is not None:
                self.budget.openalex_remaining_usd = float(rem)
        except ValueError:
            pass
        if r.status == 403 and b"key_not_activated" in r.body:
            self.key_inactive = True

    async def _get(self, url: str, params: dict | None = None) -> HttpResult:
        r = await self.http.get(url, self._headers(), params)
        if r.status == 403 and self.api_key and b"key_not_activated" in r.body:
            # the emailed link was not clicked yet: carry on keyless
            self.api_key = None
            self.key_inactive = True
            r = await self.http.get(url, {}, params)
        self._note(r)
        return r

    async def works_by_dois(self, dois: list[str]) -> dict[str, OpenAlexWork]:
        """Batch lookup (up to 100 DOIs per call). The filter also matches location DOIs."""
        found: dict[str, OpenAlexWork] = {}
        todo = []
        for d in dict.fromkeys(dois):
            cached = self.cache.get_work(doi=d)
            if cached:
                found[d] = parse_work(cached)
            else:
                todo.append(d)
        for i in range(0, len(todo), 100):
            batch = todo[i : i + 100]
            r = await self._get(
                f"{API}/works",
                {"filter": "doi:" + "|".join(batch), "per_page": 100, "select": SELECT},
            )
            if r.status != 200:
                continue
            for raw in r.json().get("results", []):
                work = parse_work(raw)
                self.cache.put_work(raw)
                for d in batch:
                    if d == work.doi:
                        found[d] = work
        # a preprint DOI can match a work whose primary DOI differs; try singletons for the rest
        for d in todo:
            if d not in found:
                w = await self.work_by_ref(f"doi:{d}")
                if w:
                    found[d] = w
        return found

    async def work_by_ref(self, ref: str) -> OpenAlexWork | None:
        """Singleton lookup: `doi:10.x/y`, `pmid:123` or `W123`. Free of charge."""
        r = await self._get(f"{API}/works/{quote(ref, safe=':/')}", {"select": SELECT})
        if r.status != 200:
            return None
        raw = r.json()
        self.cache.put_work(raw)
        return parse_work(raw)

    async def search_title(self, entry: BibEntry) -> OpenAlexWork | None:
        if not entry.title:
            return None
        params = {"search.title": entry.title, "per_page": 5, "select": SELECT}
        if entry.year and entry.year.isdigit():
            y = int(entry.year)
            params["filter"] = f"publication_year:{y - 1}-{y + 1}"
        r = await self._get(f"{API}/works", params)
        if r.status != 200:
            return None
        for raw in r.json().get("results", []):
            cand = parse_work(raw)
            if accept_title_match(entry, cand):
                self.cache.put_work(raw)
                return cand
        return None

    async def resolve_all(self, entries: list[BibEntry]) -> dict[str, OpenAlexWork | None]:
        out: dict[str, OpenAlexWork | None] = {}
        by_doi = await self.works_by_dois([e.lookup_doi for e in entries if e.lookup_doi])
        for e in entries:
            work = by_doi.get(e.lookup_doi) if e.lookup_doi else None
            if work is None and e.pmid:
                work = await self.work_by_ref(f"pmid:{e.pmid}")
            if work is None and not e.doi:
                work = await self.search_title(e)
            out[e.key] = work
        return out

    async def download_content(self, work: OpenAlexWork, kind: str = "pdf") -> bytes | None:
        """Paid download ($0.01); the caller checks the budget first."""
        ext = "pdf" if kind == "pdf" else "grobid-xml"
        r = await self._get(f"{CONTENT}/works/{work.openalex_id}.{ext}")
        self._note(r)
        if r.status != 200:
            return None
        self.budget.openalex_spent += RunBudget.CONTENT_COST
        return r.body


def doi_title_mismatch(entry: BibEntry, work: OpenAlexWork) -> float | None:
    """Fuzzy score between the entry and the work its DOI resolves to (None if not comparable)."""
    if not entry.title or not work.title:
        return None
    return fuzz.token_set_ratio(norm(entry.title), norm(work.title))
