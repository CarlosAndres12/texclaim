"""arXiv PDF downloads under its usage limits (PLAN §7.2)."""

from __future__ import annotations

from texclaim.sources.budget import RunBudget
from texclaim.sources.http import HttpClient, is_pdf


class ArxivClient:
    def __init__(self, http: HttpClient, budget: RunBudget) -> None:
        self.http, self.budget = http, budget
        for host in ("arxiv.org", "export.arxiv.org"):
            http.set_interval(host, 3.0)

    async def download(self, arxiv_id: str) -> bytes | None:
        """PDF bytes, or None. A 403/429 stops all further arXiv use in this run."""
        if not self.budget.can_use_arxiv():
            return None
        self.budget.arxiv_downloads += 1
        r = await self.http.get(f"https://arxiv.org/pdf/{arxiv_id}")
        if r.status in (403, 429):
            self.budget.arxiv_blocked = True
            return None
        if r.status == 200 and is_pdf(r.body):
            return r.body
        return None
