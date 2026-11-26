"""Minimal stdio MCP server exposing a paper's knowledge graph to agents (CodeGraph-style).

Run `texclaim mcp <paper>` and register it in an MCP client, e.g.
`claude mcp add texclaim -- texclaim mcp /path/to/paper`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import texclaim
from texclaim.graph.build import load_graph

PROTOCOL = "2025-06-18"

TOOLS = [
    {
        "name": "graph_search",
        "description": "Find nodes (claims, works, entities, sections) whose label or text "
        "contains the query. Optional kind filter: claim | work | entity | section.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "kind": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "graph_neighbors",
        "description": "Nodes connected to a node id (both directions), with edge kinds and "
        "verdicts. Use depth 2 to explore further.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "depth": {"type": "integer", "default": 1}},
            "required": ["id"],
        },
    },
    {
        "name": "claim_detail",
        "description": "Full text, location, verdicts, quotes and explanation for a claim id "
        "(claim:<n>) from the latest report.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "findings",
        "description": "Flagged results of the latest check (contradicted, partially supported, "
        "not found, needs review). Optional origin filter: cited | internal.",
        "inputSchema": {"type": "object", "properties": {"origin": {"type": "string"}}},
    },
]


class GraphTools:
    def __init__(self, folder: Path) -> None:
        self.folder = folder.resolve()

    def _graph(self) -> dict:
        g = load_graph(self.folder)
        if g is None:
            raise ValueError("no knowledge graph yet; run `texclaim check` first")
        return g

    def _report(self) -> dict:
        p = self.folder / "texclaim_report.json"
        if not p.exists():
            raise ValueError("no report yet; run `texclaim check` first")
        return json.loads(p.read_text(encoding="utf-8"))

    @staticmethod
    def _brief(n: dict) -> dict:
        keep = ("id", "kind", "label", "verdict", "role", "origin", "etype", "file", "line")
        return {k: n[k] for k in keep if n.get(k) is not None}

    def graph_search(self, query: str, kind: str | None = None, limit: int = 20) -> list[dict]:
        q = query.lower()
        hits = [
            n for n in self._graph()["nodes"]
            if (not kind or n["kind"] == kind)
            and (q in str(n.get("label", "")).lower() or q in str(n.get("text", "")).lower())
        ]  # fmt: skip
        hits.sort(key=lambda n: -n.get("pagerank", 0))
        return [self._brief(n) for n in hits[: max(1, min(limit, 100))]]

    def graph_neighbors(self, id: str, depth: int = 1) -> dict:  # noqa: A002 - MCP arg name
        g = self._graph()
        nodes = {n["id"]: n for n in g["nodes"]}
        if id not in nodes:
            raise ValueError(f"unknown node id: {id}")
        frontier, seen, edges = {id}, {id}, []
        for _ in range(max(1, min(depth, 3))):
            nxt = set()
            for e in g["edges"]:
                if e["source"] in frontier or e["target"] in frontier:
                    edges.append({k: e.get(k) for k in ("source", "target", "kind", "verdict")})
                    for x in (e["source"], e["target"]):
                        if x not in seen:
                            seen.add(x)
                            nxt.add(x)
            frontier = nxt
        return {"nodes": [self._brief(nodes[x]) for x in seen], "edges": edges[:500]}

    def claim_detail(self, id: str) -> dict:  # noqa: A002
        g = self._graph()
        node = next((n for n in g["nodes"] if n["id"] == id and n["kind"] == "claim"), None)
        if node is None:
            raise ValueError(f"unknown claim id: {id}")
        rep = self._report()
        units = [
            {k: u.get(k) for k in ("bib_key", "verdict", "analysis", "what_is_wrong",
                                   "what_source_says", "suggested_fix", "quotes", "confidence")}
            for u in rep["units"]
            if u["file"] == node.get("file") and u["line"] == node.get("line")
            and u["claim_text"] == node.get("text")
        ]  # fmt: skip
        return {**self._brief(node), "text": node.get("text"), "results": units}

    def findings(self, origin: str | None = None) -> list[dict]:
        out = []
        for f in self._report()["findings"]:
            if f.get("kind") != "unit" or f.get("suppressed"):
                continue
            if origin and f.get("claim_origin", "cited") != origin:
                continue
            out.append(
                {
                    k: f.get(k)
                    for k in (
                        "id",
                        "verdict",
                        "bib_key",
                        "file",
                        "line",
                        "claim_text",
                        "what_is_wrong",
                        "role",
                    )
                }
            )
        return out


def handle(tools: GraphTools, msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:  # notification
        return None
    try:
        if method == "initialize":
            result = {
                "protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "texclaim", "version": texclaim.__version__},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            p = msg.get("params", {})
            name, args = p.get("name"), p.get("arguments") or {}
            if name not in {t["name"] for t in TOOLS}:
                raise ValueError(f"unknown tool: {name}")
            try:
                data = getattr(tools, name)(**args)
                result = {
                    "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]
                }
            except (ValueError, TypeError) as e:
                result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
        else:
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            }
    except Exception as e:  # noqa: BLE001
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve_stdio(folder: Path) -> None:
    tools = GraphTools(folder)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        resp = handle(tools, msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
