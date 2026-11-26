"""Provider cascade: find usable text for every cited work (PLAN §7.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from rapidfuzz import fuzz

from texclaim.config import Settings
from texclaim.parser.bib_parser import BibEntry
from texclaim.sources.arxiv_client import ArxivClient
from texclaim.sources.budget import RunBudget
from texclaim.sources.global_cache import GlobalCache
from texclaim.sources.http import HttpClient, HttpError, OfflineError, is_pdf
from texclaim.sources.identity import check_identity, first_pages_text, norm
from texclaim.sources.openalex_client import OpenAlexClient, OpenAlexWork


@dataclass
class Validation:
    ok: bool
    code: str = ""  # SOURCE_IDENTITY_MISMATCH | EXTRACTION_FAILED | SCANNED_PDF
    detail: str = ""


class SourceValidator(Protocol):
    def check(self, data: bytes, entry: BibEntry) -> Validation: ...


class IdentityValidator:
    """Default validator: the first two pages must carry the entry's title or author."""

    def check(self, data: bytes, entry: BibEntry) -> Validation:
        try:
            text = first_pages_text(data)
        except Exception as e:  # noqa: BLE001 - corrupt PDF
            return Validation(False, "EXTRACTION_FAILED", type(e).__name__)
        res = check_identity(text, entry.title, entry.first_surname)
        return Validation(res.ok, "" if res.ok else "SOURCE_IDENTITY_MISMATCH", res.detail)


class ExtractingValidator:
    """Extracts (once, via the global text cache), then rejects scanned PDFs and wrong works."""

    def __init__(self, cache: GlobalCache, extractor=None) -> None:
        self.cache, self.extractor = cache, extractor

    def check(self, data: bytes, entry: BibEntry) -> Validation:
        from texclaim.sources.extractor import extract_cached

        try:
            _, doc = extract_cached(data, self.cache, self.extractor)
        except Exception as e:  # noqa: BLE001 - corrupt or encrypted PDF
            return Validation(False, "EXTRACTION_FAILED", type(e).__name__)
        if doc.scanned:
            return Validation(False, "SCANNED_PDF", "no text layer; OCR is not supported")
        head = "\n".join(p.text for p in doc.pages[:2])
        res = check_identity(head, entry.title, entry.first_surname)
        return Validation(res.ok, "" if res.ok else "SOURCE_IDENTITY_MISMATCH", res.detail)


@dataclass
class SourceResult:
    key: str
    status: str  # FULL_TEXT | ABSTRACT_ONLY | NO_SOURCE | SOURCE_IDENTITY_MISMATCH | ...
    provider: str | None = None
    version: str | None = None
    blob_sha256: str | None = None
    abstract: str | None = None
    work: OpenAlexWork | None = None
    trail: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)  # {"code", "provider", "sha256", "detail"}
    text_sha256: str | None = None  # fingerprint of the text the verifier will see
    language: str | None = None


class Locator:
    def __init__(
        self,
        paper: Path,
        settings: Settings,
        cache: GlobalCache,
        *,
        http: HttpClient | None = None,
        openalex: OpenAlexClient | None = None,
        arxiv: ArxivClient | None = None,
        budget: RunBudget | None = None,
        validator: SourceValidator | None = None,
        pdf_dirs: list[Path] | None = None,
        asta=None,
    ) -> None:
        self.paper = paper.resolve()
        self.settings = settings
        self.cache = cache
        self.http, self.openalex, self.arxiv = http, openalex, arxiv
        self.asta = asta
        self._asta: dict[str, dict | None] = {}
        self.budget = budget or RunBudget()
        self.validator = validator or IdentityValidator()
        dirs = pdf_dirs if pdf_dirs is not None else [Path(d) for d in settings.pdf_dirs]
        self.pdf_dirs = [d if d.is_absolute() else self.paper / d for d in dirs]
        self.offline = settings.offline or http is None or http.offline
        self._pdf_index: list[tuple[Path, str]] | None = None

    # ---- public -----------------------------------------------------------------------
    async def locate_all(self, entries: list[BibEntry]) -> dict[str, SourceResult]:
        works: dict[str, OpenAlexWork | None] = {}
        if self.openalex and not self.offline:
            try:
                works = await self.openalex.resolve_all(entries)
            except (HttpError, OfflineError):
                works = {}
        else:  # offline: use what the global cache already holds
            from texclaim.sources.openalex_client import parse_work

            for e in entries:
                raw = e.lookup_doi and self.cache.get_work(doi=e.lookup_doi)
                works[e.key] = parse_work(raw) if raw else None
        if self.asta is not None and not self.offline and "asta" in self.settings.sources.order:
            from texclaim.sources.asta_client import asta_refs

            refs = [r for e in entries for r in asta_refs(e, works.get(e.key))]
            if refs:
                self._asta = await self.asta.papers(refs)
        return {e.key: await self.locate(e, works.get(e.key)) for e in entries}

    async def locate(self, entry: BibEntry, work: OpenAlexWork | None) -> SourceResult:
        res = SourceResult(entry.key, "NO_SOURCE", work=work)
        for provider in self.settings.sources.order:
            fn = getattr(self, f"_p_{provider}", None)
            if fn is None:
                continue
            hit = await fn(entry, work, res)
            if hit:
                return res
        if res.abstract:
            res.status, res.provider = "ABSTRACT_ONLY", "abstract"
        elif any(f["code"] == "SOURCE_IDENTITY_MISMATCH" for f in res.failures):
            res.status = "SOURCE_IDENTITY_MISMATCH"
        elif any(f["code"] == "SCANNED_PDF" for f in res.failures):
            res.status = "SCANNED_PDF"
        elif any(f["code"] == "EXTRACTION_FAILED" for f in res.failures):
            res.status = "EXTRACTION_FAILED"
        return res

    # ---- helpers ------------------------------------------------------------------------
    def _note(self, res: SourceResult, provider: str, outcome: str, detail: str = "") -> None:
        res.trail.append({"provider": provider, "outcome": outcome, "detail": detail})

    def _accept(
        self, res: SourceResult, entry: BibEntry, work: OpenAlexWork | None, data: bytes,
        provider: str, version: str | None, url: str | None = None,
    ) -> bool:  # fmt: skip
        sha = self.cache.put_blob(data, "application/pdf", url)
        v = self.validator.check(data, entry)
        if not v.ok:
            res.failures.append(
                {"code": v.code, "provider": provider, "sha256": sha, "detail": v.detail}
            )
            self._note(res, provider, v.code.lower(), v.detail)
            return False
        for id_type, value in self._ids(entry, work):
            self.cache.set_identifier(id_type, value, sha, provider, version)
        res.status, res.provider, res.version, res.blob_sha256 = "FULL_TEXT", provider, version, sha
        self._note(res, provider, "hit", sha[:12])
        return True

    @staticmethod
    def _ids(entry: BibEntry, work: OpenAlexWork | None) -> list[tuple[str, str]]:
        ids = []
        if entry.doi:
            ids.append(("doi", entry.doi))
        if entry.lookup_doi:
            ids.append(("doi", entry.lookup_doi))
        if entry.arxiv_id:
            ids.append(("arxiv", entry.arxiv_id))
        if work:
            ids.append(("openalex", work.openalex_id))
            if work.doi:
                ids.append(("doi", work.doi))
        return list(dict.fromkeys(ids))

    # ---- providers ----------------------------------------------------------------------
    def _index(self) -> list[tuple[Path, str]]:
        if self._pdf_index is None:
            self._pdf_index = []
            for d in self.pdf_dirs:
                for p in sorted(d.rglob("*.pdf")) if d.is_dir() else []:
                    try:
                        text = norm(first_pages_text(p.read_bytes(), 1))
                    except Exception:  # noqa: BLE001
                        text = ""
                    self._pdf_index.append((p, text))
        return self._pdf_index

    async def _p_local(self, entry: BibEntry, work, res: SourceResult) -> bool:
        cands: list[Path] = []
        for f in entry.local_files:
            p = Path(f)
            cands.append(p if p.is_absolute() else self.paper / p)
        cands += [d / f"{entry.key}.pdf" for d in self.pdf_dirs]
        for p, text in self._index():
            if p in cands or not text:
                continue
            by_doi = entry.doi and norm(entry.doi) in text
            by_title = entry.title and fuzz.partial_ratio(norm(entry.title), text) >= 90
            if by_doi or by_title:
                cands.append(p)
        seen = set()
        for p in cands:
            if p in seen or not p.is_file():
                continue
            seen.add(p)
            data = p.read_bytes()
            if data[:5] != b"%PDF-":
                self._note(res, "local", "not_a_pdf", p.name)
                continue
            if self._accept(res, entry, work, data, "local", None):
                return True
        if not seen:
            self._note(res, "local", "miss")
        return False

    async def _p_cache(self, entry: BibEntry, work, res: SourceResult) -> bool:
        for id_type, value in self._ids(entry, work):
            row = self.cache.lookup_identifier(id_type, value)
            if not row:
                continue
            path = self.cache.get_blob(row["sha256"])
            if path and self._accept(res, entry, work, path.read_bytes(), "cache", row["version"]):
                res.provider = "cache"
                return True
        self._note(res, "cache", "miss")
        return False

    async def _p_openalex_content(self, entry: BibEntry, work, res: SourceResult) -> bool:
        o = self.openalex
        if self.offline or o is None or not o.api_key:
            self._note(res, "openalex_content", "skipped", "no key or offline")
            return False
        if work is None or not work.has_pdf_content:
            self._note(res, "openalex_content", "miss", "no content")
            return False
        if not self.budget.can_buy_content():
            self._note(res, "openalex_content", "skipped", "budget")
            return False
        if self.cache.is_negative("openalex", work.openalex_id, "openalex_content"):
            self._note(res, "openalex_content", "negative_cache")
            return False
        try:
            data = await o.download_content(work)
        except HttpError as e:
            self._note(res, "openalex_content", "error", str(e))
            return False
        if data is None or not is_pdf(data):
            self.cache.add_negative("openalex", work.openalex_id, "openalex_content", "no pdf")
            self._note(res, "openalex_content", "miss")
            return False
        return self._accept(res, entry, work, data, "openalex_content", "publishedVersion")

    async def _p_oa_locations(self, entry: BibEntry, work, res: SourceResult) -> bool:
        if self.offline or self.http is None or work is None or not work.locations:
            self._note(res, "oa_locations", "skipped", "offline or no locations")
            return False
        if self.cache.is_negative("openalex", work.openalex_id, "oa_locations"):
            self._note(res, "oa_locations", "negative_cache")
            return False
        for loc in work.locations:
            try:
                r = await self.http.get(loc.pdf_url)
            except HttpError as e:
                self._note(res, "oa_locations", "error", str(e))
                continue
            if r.status == 200 and is_pdf(r.body):
                if self._accept(res, entry, work, r.body, "oa_locations", loc.version, loc.pdf_url):
                    return True
            else:
                reason = "NOT_A_PDF" if r.status == 200 else f"http_{r.status}"
                self._note(res, "oa_locations", reason.lower(), loc.pdf_url)
        if not any(t["provider"] == "oa_locations" and t["outcome"] == "error" for t in res.trail):
            self.cache.add_negative("openalex", work.openalex_id, "oa_locations", "no usable pdf")
        return False

    async def _p_arxiv(self, entry: BibEntry, work, res: SourceResult) -> bool:
        aid = entry.arxiv_id or (work.arxiv_id if work else None)
        if self.offline or self.arxiv is None or not aid:
            self._note(res, "arxiv", "skipped", "offline or no arXiv id")
            return False
        if self.cache.is_negative("arxiv", aid, "arxiv"):
            self._note(res, "arxiv", "negative_cache")
            return False
        if not self.budget.can_use_arxiv():
            self._note(res, "arxiv", "skipped", "limit or blocked")
            return False
        try:
            data = await self.arxiv.download(aid)
        except HttpError as e:
            self._note(res, "arxiv", "error", str(e))
            return False
        if data is None:
            if not self.budget.arxiv_blocked:
                self.cache.add_negative("arxiv", aid, "arxiv", "no pdf")
            self._note(res, "arxiv", "miss")
            return False
        return self._accept(res, entry, work, data, "arxiv", "submittedVersion", f"arxiv:{aid}")

    async def _p_asta(self, entry: BibEntry, work, res: SourceResult) -> bool:
        """Asta / Semantic Scholar: open-access PDF link, else an abstract for the fallback."""
        if self.offline or self.asta is None or self.http is None:
            self._note(res, "asta", "skipped", "offline or no ASTA_API_KEY")
            return False
        from texclaim.sources.asta_client import asta_refs

        paper = None
        for ref in asta_refs(entry, work):
            paper = self._asta.get(ref)
            if paper:
                break
        if paper is None and entry.title and not asta_refs(entry, work):
            paper = await self.asta.by_title(entry.title)
            if paper and not _title_matches(entry.title, paper.get("title") or ""):
                self._note(res, "asta", "title_mismatch", paper.get("title") or "")
                paper = None
        if not paper:
            self._note(res, "asta", "miss")
            return False
        pdf = (paper.get("openAccessPdf") or {}).get("url")
        if pdf:
            try:
                r = await self.http.get(pdf)
            except HttpError as e:
                self._note(res, "asta", "error", str(e))
                r = None
            if r is not None and r.status == 200 and is_pdf(r.body):
                if self._accept(res, entry, work, r.body, "asta", None, pdf):
                    return True
            elif r is not None:
                self._note(res, "asta", f"http_{r.status}" if r.status != 200 else "not_a_pdf", pdf)
        abstract = paper.get("abstract") or ((paper.get("tldr") or {}).get("text"))
        if abstract and not res.abstract:
            res.abstract = abstract
            self._note(res, "asta", "abstract")
        else:
            self._note(res, "asta", "no_pdf")
        return False

    async def _p_abstract(self, entry: BibEntry, work, res: SourceResult) -> bool:
        if work and work.abstract:
            res.abstract = work.abstract
            self._note(res, "abstract", "available")
        else:
            self._note(res, "abstract", "miss")
        return False  # the cascade falls through to ABSTRACT_ONLY at the end


def _title_matches(a: str, b: str) -> bool:
    from rapidfuzz import fuzz

    return fuzz.token_set_ratio(a.lower(), b.lower()) >= 90
