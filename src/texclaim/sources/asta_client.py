"""Asta Scientific Corpus Tools (Ai2, Semantic Scholar data) over its MCP HTTP endpoint.

Used as a late provider in the source cascade: open-access PDF links and abstracts for works that
OpenAlex and arXiv could not supply. Calls are slow (tens of seconds), so lookups are batched,
cached on disk for 30 days, and skipped entirely without a key or when offline.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

ENDPOINT = "https://asta-tools.allen.ai/mcp/v1"
FIELDS = "title,year,externalIds,openAccessPdf,abstract,tldr,authors"
TTL = 30 * 86400


class AstaClient:
    def __init__(self, api_key: str, cache_dir: Path, timeout: float = 180.0) -> None:
        self.key = api_key
        self.dir = cache_dir / "asta"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self._id = 0
        self.calls = 0
        self.disabled = False

    # ---- cache ------------------------------------------------------------------------
    def _path(self, ref: str) -> Path:
        return self.dir / (hashlib.sha256(ref.lower().encode()).hexdigest()[:32] + ".json")

    def cached(self, ref: str) -> dict | None | bool:
        """The cached paper dict, None for a cached miss, False when not cached."""
        p = self._path(ref)
        try:
            if time.time() - p.stat().st_mtime > TTL:
                return False
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False

    def _store(self, ref: str, paper: dict | None) -> None:
        self._path(ref).write_text(json.dumps(paper), encoding="utf-8")

    # ---- transport ------------------------------------------------------------------------
    async def _call(self, tool: str, arguments: dict) -> object | None:
        if self.disabled:
            return None
        self._id += 1
        self.calls += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                "params": {"name": tool, "arguments": arguments}}  # fmt: skip
        headers = {
            "x-api-key": self.key,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(ENDPOINT, json=body, headers=headers)
        except httpx.HTTPError as e:
            log.debug("asta %s failed: %s", tool, type(e).__name__)
            return None
        if r.status_code in (401, 403):
            self.disabled = True  # bad key: stop for this run
            return None
        if r.status_code != 200:
            return None
        return parse_sse_result(r.text)

    # ---- API ------------------------------------------------------------------------------
    async def papers(self, refs: list[str]) -> dict[str, dict | None]:
        """refs like 'DOI:10.x/y' or 'ARXIV:1706.03762' -> paper dict or None (cached)."""
        out: dict[str, dict | None] = {}
        todo = []
        for ref in dict.fromkeys(refs):
            c = self.cached(ref)
            if c is False:
                todo.append(ref)
            else:
                out[ref] = c  # type: ignore[assignment]
        for i in range(0, len(todo), 100):
            chunk = todo[i : i + 100]
            res = await self._call("get_paper_batch", {"ids": chunk, "fields": FIELDS})
            items = res if isinstance(res, list) else ([res] if isinstance(res, dict) else None)
            if items is None:
                for ref in chunk:  # transport problem: do not cache misses
                    out.setdefault(ref, None)
                continue
            # Unknown ids are dropped from the reply, so match by external ids, not position
            found: dict[str, dict] = {}
            for paper in items:
                if isinstance(paper, dict) and paper.get("title"):
                    for ref in paper_refs(paper):
                        found[ref] = paper
            if len(items) == len(chunk):  # aligned reply: positions are reliable too
                for ref, paper in zip(chunk, items, strict=True):
                    if isinstance(paper, dict) and paper.get("title"):
                        found.setdefault(ref.upper(), paper)
            for ref in chunk:
                paper = found.get(ref.upper())
                self._store(ref, paper)
                out[ref] = paper
        return out

    async def by_title(self, title: str) -> dict | None:
        ref = "TITLE:" + " ".join(title.lower().split())
        c = self.cached(ref)
        if c is not False:
            return c  # type: ignore[return-value]
        res = await self._call("search_paper_by_title", {"title": title, "fields": FIELDS})
        paper = None
        if isinstance(res, list) and res:
            paper = res[0] if isinstance(res[0], dict) else None
        elif isinstance(res, dict):
            data = res.get("data")
            paper = data[0] if isinstance(data, list) and data else res
        if res is not None:
            self._store(ref, paper if paper and paper.get("title") else None)
        return paper if paper and paper.get("title") else None


def parse_sse_result(text: str) -> object | None:
    """The tool result from an MCP streamable-HTTP reply (SSE `data:` lines or plain JSON)."""
    payloads = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
    if not payloads and text.strip().startswith("{"):
        payloads = [text.strip()]
    for p in payloads:
        try:
            msg = json.loads(p)
        except ValueError:
            continue
        result = msg.get("result") if isinstance(msg, dict) else None
        if not isinstance(result, dict) or result.get("isError"):
            continue
        if "structuredContent" in result:
            sc = result["structuredContent"]
            return sc.get("result", sc) if isinstance(sc, dict) else sc
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        if not texts:
            return None
        if len(texts) > 1:  # one item per content block
            items = []
            for t in texts:
                try:
                    items.append(json.loads(t))
                except ValueError:
                    items.append(None)
            return items
        try:
            return json.loads(texts[0])
        except ValueError:
            return None
    return None


def paper_refs(paper: dict) -> list[str]:
    ids = paper.get("externalIds") or {}
    refs = []
    if ids.get("DOI"):
        refs.append("DOI:" + str(ids["DOI"]).upper())
    if ids.get("ArXiv"):
        refs.append("ARXIV:" + str(ids["ArXiv"]).upper())
    return refs


def asta_refs(entry, work) -> list[str]:
    refs = []
    doi = entry.doi or (work.doi if work else None)
    if doi:
        refs.append("DOI:" + doi)
    aid = entry.arxiv_id or (work.arxiv_id if work else None)
    if aid:
        refs.append("ARXIV:" + aid)
    return refs
