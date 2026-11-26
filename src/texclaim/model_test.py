"""Quick connectivity checks for a model, an agent CLI, OpenAlex and Asta (used by GUI and CLI)."""

from __future__ import annotations

import time

PING_SYSTEM = "You are a health check. Reply with exactly the word OK."


async def test_model(model: str) -> dict:
    """Send one tiny prompt. Returns {ok, seconds, reply | error}; never raises."""
    t0 = time.monotonic()
    try:
        if model == "demo":
            return {"ok": True, "seconds": 0.0, "reply": "OK (demo verifier, no model calls)"}
        if model.startswith("cli:"):
            from texclaim.verifier.cli_agent import CliAgentVerifier

            v = CliAgentVerifier(model, timeout=120)
            res = await v.run(PING_SYSTEM, "Health check: reply OK.")
            reply = res.text.strip()
        else:
            import litellm

            litellm.suppress_debug_info = True
            r = await litellm.acompletion(
                model=model,
                messages=[{"role": "system", "content": PING_SYSTEM},
                          {"role": "user", "content": "Health check: reply OK."}],
                max_tokens=10, timeout=60, num_retries=0,
            )  # fmt: skip
            reply = (r.choices[0].message.content or "").strip()
        return {"ok": True, "seconds": round(time.monotonic() - t0, 1), "reply": reply[:80]}
    except Exception as e:  # noqa: BLE001 - report any provider/CLI failure to the user
        msg = f"{type(e).__name__}: {e}"
        for secret_hint in ("sk-", "key="):  # never echo something that looks like a key
            if secret_hint in msg:
                msg = msg.split(secret_hint)[0] + "[redacted]"
        return {"ok": False, "seconds": round(time.monotonic() - t0, 1), "error": msg[:400]}


async def test_openalex(key: str | None) -> dict:
    import httpx

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            params = {"select": "id,title"}
            if key:
                params["api_key"] = key
            r = await c.get("https://api.openalex.org/works/doi:10.48550/arXiv.1706.03762",
                            params=params)  # fmt: skip
        ok = r.status_code == 200
        return {"ok": ok, "seconds": round(time.monotonic() - t0, 1),
                **({"reply": "OpenAlex reachable" + (" (key accepted)" if key else " (no key)")}
                   if ok else {"error": f"HTTP {r.status_code}: {r.text[:200]}"})}  # fmt: skip
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "seconds": round(time.monotonic() - t0, 1), "error": str(e)[:300]}


async def test_asta(key: str | None) -> dict:
    import httpx

    t0 = time.monotonic()
    if not key:
        return {"ok": False, "seconds": 0.0, "error": "ASTA_API_KEY is not set"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "texclaim", "version": "0"}}}  # fmt: skip
    headers = {"x-api-key": key, "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}  # fmt: skip
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post("https://asta-tools.allen.ai/mcp/v1", json=body, headers=headers)
        ok = r.status_code == 200 and "serverInfo" in r.text
        return {"ok": ok, "seconds": round(time.monotonic() - t0, 1),
                **({"reply": "Asta reachable, key accepted"} if ok
                   else {"error": f"HTTP {r.status_code}: {r.text[:200]}"})}  # fmt: skip
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "seconds": round(time.monotonic() - t0, 1), "error": str(e)[:300]}
