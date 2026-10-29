"""Bibliography parsing with bibtexparser 2.x (PLAN §6.7)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import bibtexparser
from bibtexparser import middlewares as mw
from bibtexparser.model import DuplicateBlockKeyBlock, ParsingFailedBlock

from texclaim.models import Diagnostic, SourceFile
from texclaim.parser.latex_graph import BibResource
from texclaim.parser.text import collapse

_DOI = re.compile(r"10\.\d{4,9}/[^\s\"<>{}]+", re.I)
_ARXIV_NEW = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5})(?:v\d+)?(?![\d])")
_ARXIV_URL = re.compile(
    r"arxiv\.org/(?:abs|pdf)/([a-z\-]+(?:\.[A-Za-z]{2})?/\d{7}|\d{4}\.\d{4,5})", re.I
)
_ARXIV_PREFIX = re.compile(r"arxiv:\s*([a-z\-]+(?:\.[A-Za-z]{2})?/\d{7}|\d{4}\.\d{4,5})", re.I)
_FAILED_KEY = re.compile(r"@\w+\s*[{(]\s*([^,\s]+)\s*,")
REQUIRED_FIELDS = ("title", "author", "year")


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    m = _DOI.search(value.strip())
    if not m:
        return None
    doi = m.group(0).rstrip(".,;")
    while doi.endswith(")") and doi.count("(") < doi.count(")"):
        doi = doi[:-1].rstrip(".,;")
    return doi.lower()


def extract_arxiv_id(*texts: str | None) -> str | None:
    """arXiv ID without version, from `arXiv:` prefixes and arxiv.org URLs."""
    for t in texts:
        if not t:
            continue
        for rx in (_ARXIV_URL, _ARXIV_PREFIX):
            m = rx.search(t)
            if m:
                return re.sub(r"v\d+$", "", m.group(1))
    return None


def arxiv_doi(arxiv_id: str) -> str:
    return f"10.48550/arxiv.{arxiv_id.lower()}"


def _file_field(value: str) -> list[str]:
    """Local file paths from JabRef (`:path:PDF`), Zotero (`desc:path:type`) or plain `a;b`."""
    out = []
    for item in value.split(";"):
        parts = item.split(":")
        path = parts[1] if len(parts) >= 3 else item
        path = path.strip()
        if path.lower().endswith(".pdf"):
            out.append(path)
    return out


def _name(n) -> dict[str, str]:
    def j(parts):
        return " ".join(parts).replace("{", "").replace("}", "")

    return {"first": j(n.first), "last": j(n.von + n.last)}


@dataclass
class BibEntry:
    key: str
    bib_file: str
    entry_type: str
    title: str | None
    authors: list[dict[str, str]]
    year: str | None
    doi: str | None  # declared DOI only
    arxiv_id: str | None
    pmid: str | None
    local_files: list[str]
    entry_hash: str
    missing_fields: list[str]
    raw_fields: dict[str, str] = field(default_factory=dict, repr=False)
    line: int | None = None  # 1-based line of the entry in its .bib file

    @property
    def lookup_doi(self) -> str | None:
        return self.doi or (arxiv_doi(self.arxiv_id) if self.arxiv_id else None)

    @property
    def first_surname(self) -> str | None:
        return self.authors[0]["last"] if self.authors else None


@dataclass
class BibDatabase:
    entries: dict[str, BibEntry] = field(default_factory=dict)
    duplicates: dict[str, list[str]] = field(default_factory=dict)  # key -> files defining it
    malformed: dict[str, str] = field(default_factory=dict)  # key -> file
    files: list[SourceFile] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


def _entry_from(e, bib_file: str) -> BibEntry:
    f = {k: collapse(str(v.value if hasattr(v, "value") else v)) for k, v in e.fields_dict.items()}
    f = {k.lower(): v for k, v in f.items()}
    raw_author = e.fields_dict["author"].value if "author" in e.fields_dict else None
    authors = (
        [_name(n) for n in raw_author if hasattr(n, "last")] if isinstance(raw_author, list) else []
    )
    title = f.get("title", "").replace("{", "").replace("}", "").strip() or None
    url_blob = " ".join(f.get(k, "") for k in ("url", "note", "journal", "howpublished"))
    doi = normalize_doi(f.get("doi")) or (
        normalize_doi(f.get("url")) if "doi.org" in f.get("url", "").lower() else None
    )
    arxiv = None
    if f.get("archiveprefix", "").lower() == "arxiv" or f.get("eprinttype", "").lower() == "arxiv":
        arxiv = extract_arxiv_id(f"arxiv:{f.get('eprint', '')}")
    arxiv = arxiv or extract_arxiv_id(url_blob, f.get("eprint"))
    pmid = f.get("pmid") or None
    year = (re.search(r"\d{4}", f.get("year", "") or f.get("date", "")) or [None])[0]
    missing = [
        n for n, present in (("title", title), ("author", authors), ("year", year)) if not present
    ]
    norm = {
        "key": e.key, "type": e.entry_type, "title": (title or "").lower(),
        "authors": [(a["last"], a["first"]) for a in authors], "year": year,
        "doi": doi, "arxiv": arxiv, "pmid": pmid,
    }  # fmt: skip
    digest = hashlib.sha256(
        json.dumps(norm, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return BibEntry(
        key=e.key,
        bib_file=bib_file,
        entry_type=e.entry_type,
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        arxiv_id=arxiv,
        pmid=pmid,
        local_files=_file_field(f.get("file", "")),
        entry_hash=digest,
        missing_fields=missing,
        raw_fields=f,
        line=(getattr(e, "start_line", None) or 0) + 1
        if getattr(e, "start_line", None) is not None
        else None,
    )


def resolve_bib_paths(resources: list[BibResource], root_dir: Path, paper: Path):
    """(resource, name, path-or-None) for every named .bib file."""
    out = []
    for res in resources:
        names = [n.strip() for n in res.raw.split(",")] if res.kind == "bibliography" else [res.raw]
        for n in filter(None, names):
            fname = n if n.endswith(".bib") else n + ".bib"
            found = next((p for p in (root_dir / fname, paper / fname) if p.is_file()), None)
            out.append((res, fname, found))
    return out


def parse_bib_files(paper: Path, root_rel: str, resources: list[BibResource]) -> BibDatabase:
    paper = paper.resolve()
    root_dir = (paper / root_rel).parent
    db = BibDatabase()
    seen: set[Path] = set()
    stack = [mw.LatexDecodingMiddleware(), mw.SeparateCoAuthors(), mw.SplitNameParts()]
    for res, fname, path in resolve_bib_paths(resources, root_dir, paper):
        if path is None:
            db.diagnostics.append(
                Diagnostic("MISSING_BIB_FILE", f"{fname} not found", "warning", res.file, res.line)
            )
            continue
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        rel = os.path.relpath(path, paper)
        raw = path.read_bytes()
        db.files.append(SourceFile(rel, "bib", hashlib.sha256(raw).hexdigest(), len(raw)))
        lib = bibtexparser.parse_string(
            raw.decode("utf-8-sig", errors="replace"), append_middleware=stack
        )
        for e in lib.entries:
            entry = _entry_from(e, rel)
            if e.key in db.entries:
                db.duplicates.setdefault(e.key, [db.entries[e.key].bib_file]).append(rel)
            else:
                db.entries[e.key] = entry
        for blk in lib.failed_blocks:
            if isinstance(blk, DuplicateBlockKeyBlock):
                db.duplicates.setdefault(blk.key, [rel]).append(rel)
            elif isinstance(blk, ParsingFailedBlock):
                m = _FAILED_KEY.search(getattr(blk, "raw", "") or "")
                if m:
                    db.malformed.setdefault(m.group(1), rel)
    _resolve_crossrefs(db)
    return db


def _resolve_crossrefs(db: BibDatabase) -> None:
    for e in db.entries.values():
        parent = db.entries.get(e.raw_fields.get("crossref", ""))
        if not parent:
            continue
        if not e.authors and parent.authors:
            e.authors = parent.authors
        e.year = e.year or parent.year
        e.doi = e.doi or None
        e.missing_fields = [
            n for n, v in (("title", e.title), ("author", e.authors), ("year", e.year)) if not v
        ]
