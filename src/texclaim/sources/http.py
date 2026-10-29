"""Shared async HTTP client: limits, retries, download hygiene (PLAN §7.4)."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

MAX_BYTES = 100 * 1024 * 1024
RETRY_STATUS = {429, 500, 502, 503, 504}


class OfflineError(RuntimeError):
    """A network request was attempted in --offline mode."""


class HttpError(RuntimeError):
    """Transport failure after all retries."""


@dataclass
class HttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes
    url: str

    def json(self):
        import json

        return json.loads(self.body)


class HttpClient:
    def __init__(
        self,
        user_agent: str,
        *,
        offline: bool = False,
        host_intervals: Mapping[str, float] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        retries: int = 4,
        backoff: float = 0.5,
        per_host: int = 2,
        overall: int = 6,
        max_bytes: int = MAX_BYTES,
    ) -> None:
        self.user_agent = user_agent
        self.offline = offline
        self.intervals = dict(host_intervals or {})
        self.sleep = sleep
        self.clock = clock
        self.retries = retries
        self.backoff = backoff
        self.max_bytes = max_bytes
        self._per_host_n, self._overall_n = per_host, overall
        self._client: httpx.AsyncClient | None = None
        self._overall: asyncio.Semaphore | None = None
        self._hosts: dict[str, asyncio.Semaphore] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self.request_count = 0

    def set_interval(self, host: str, seconds: float) -> None:
        self.intervals[host] = seconds

    async def aclose(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _ensure(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                follow_redirects=True,
                max_redirects=10,
                headers={"User-Agent": self.user_agent},
            )
            self._overall = asyncio.Semaphore(self._overall_n)
        return self._client

    async def _throttle(self, host: str) -> None:
        interval = self.intervals.get(host, 0)
        if not interval:
            return
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last.get(host, float("-inf")) + interval - self.clock()
            if wait > 0:
                await self.sleep(wait)
            self._last[host] = self.clock()

    async def _once(self, url: str, headers, params) -> HttpResult:
        client = self._ensure()
        async with client.stream("GET", url, headers=headers, params=params) as r:
            chunks, total = [], 0
            async for chunk in r.aiter_bytes():
                total += len(chunk)
                if total > self.max_bytes:
                    raise HttpError(f"response from {urlparse(url).netloc} exceeds size cap")
                chunks.append(chunk)
            return HttpResult(r.status_code, dict(r.headers), b"".join(chunks), str(r.url))

    async def get(
        self, url: str, headers: Mapping[str, str] | None = None, params: Mapping | None = None
    ) -> HttpResult:
        if self.offline:
            raise OfflineError(f"offline mode: refusing request to {urlparse(url).netloc}")
        self._ensure()
        host = urlparse(url).netloc
        sem = self._hosts.setdefault(host, asyncio.Semaphore(self._per_host_n))
        last_exc: Exception | None = None
        result: HttpResult | None = None
        for attempt in range(self.retries):
            async with self._overall, sem:  # type: ignore[union-attr]
                await self._throttle(host)
                self.request_count += 1
                try:
                    result = await self._once(url, headers, params)
                    last_exc = None
                except httpx.TransportError as e:
                    last_exc, result = e, None
            if result is not None and result.status not in RETRY_STATUS:
                return result
            if attempt == self.retries - 1:
                break
            delay = self.backoff * 2**attempt + random.uniform(0, self.backoff)
            if result is not None:
                ra = result.headers.get("retry-after") or result.headers.get("Retry-After")
                if ra and ra.strip().isdigit():
                    delay = max(delay, float(ra))
            await self.sleep(delay)
        if result is not None:
            return result
        raise HttpError(f"{host}: {type(last_exc).__name__}")


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-" and len(data) > 10 * 1024
