"""Per-run spending and request limits for remote sources."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunBudget:
    openalex_max_usd: float = 0.50
    arxiv_max_downloads: int = 30
    openalex_spent: float = 0.0
    arxiv_downloads: int = 0
    arxiv_blocked: bool = False
    openalex_remaining_usd: float | None = None  # from rate-limit headers when present

    CONTENT_COST = 0.01

    def can_buy_content(self) -> bool:
        if self.openalex_spent + self.CONTENT_COST > self.openalex_max_usd + 1e-9:
            return False
        rem = self.openalex_remaining_usd
        return rem is None or rem >= self.CONTENT_COST

    def can_use_arxiv(self) -> bool:
        return not self.arxiv_blocked and self.arxiv_downloads < self.arxiv_max_downloads
