"""Build the manuscript knowledge graph and save it as `.texclaim/graph.json`.

Nodes: document, section, claim (cited or internal), work (cited source), entity.
Edges: in_section, cites (with verdict), evidence (internal claim -> section/claim it rests on),
mentions (claim -> entity), about (work -> entity, via the claims citing it).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from texclaim import paths
from texclaim.graph.entities import heuristic_entities, norm_name

GRAPH_FILE = "graph.json"
GRAPH_VERSION = 1


def graph_path(folder: Path) -> Path:
    return paths.paper_state_dir(folder) / GRAPH_FILE


# ---- entity extraction (cached) ------------------------------------------------------------
async def _extract(
    conn: sqlite3.Connection, claims: list[sqlite3.Row], verifier, batch: int = 25
) -> tuple[dict[str, list[dict]], float]:
    method = getattr(verifier, "model", None) if hasattr(verifier, "extract_entities") else None
    method = method or "heuristic"
    out: dict[str, list[dict]] = {}
    todo: list[tuple[str, str]] = []
    for c in claims:
        r = conn.execute(
            "SELECT json FROM entity_cache WHERE claim_hash=? AND method=?",
            (c["claim_hash"], method),
        ).fetchone()
        if r:
            out[c["claim_hash"]] = json.loads(r["json"])
        else:
            todo.append((c["claim_hash"], c["text_norm"]))
    todo = list(dict(todo).items())
    cost = 0.0
    for i in range(0, len(todo), batch):
        chunk = todo[i : i + batch]
        got = None
        if method != "heuristic":
            got, c = await verifier.extract_entities(chunk)
            cost += c or 0.0
        if got is None:
            got = {k: heuristic_entities(t) for k, t in chunk}
        with conn:
            for k, ents in got.items():
                conn.execute(
                    "INSERT OR REPLACE INTO entity_cache VALUES (?,?,?)",
                    (k, method, json.dumps(ents, ensure_ascii=False)),
                )
        out.update(got)
    return out, cost


# ---- graph -----------------------------------------------------------------------------------
def _top(path: str | None, role: str) -> str:
    if role == "abstract" and not path:
        return "Abstract"
    return (path or "").split(" > ")[0].strip() or "Front matter"


def build_graph(conn: sqlite3.Connection, verifier=None, title: str = "Manuscript") -> dict:
    import networkx as nx

    claims = conn.execute(
        "SELECT claim_pk, claim_hash, file_path, line_start, section_path, unit_kind, text_norm,"
        " origin, role FROM claims ORDER BY claim_pk"
    ).fetchall()
    cites = conn.execute(
        "SELECT c.claim_pk, c.bib_key, c.unit_key, res.verdict, res.evidence_json,"
        " res.analysis FROM citations c LEFT JOIN current_results res"
        " ON res.unit_key = c.unit_key"
    ).fetchall()
    works = {
        r["bib_key"]: r
        for r in conn.execute(
            "SELECT bib_key, title, year, source_status, source_provider, doi"
            " FROM references_catalog"
        )
    }
    by_claim: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for r in cites:
        by_claim[r["claim_pk"]].append(r)
    # Internal claims that were never checked (screened out) are left out of the graph
    keep = [
        c for c in claims
        if c["origin"] != "internal" or any(r["verdict"] for r in by_claim[c["claim_pk"]])
    ]  # fmt: skip
    entities, cost = asyncio.run(_extract(conn, keep, verifier))

    g = nx.MultiDiGraph()
    g.add_node("doc", kind="document", label=title)
    section_pages: dict[int, str] = {}
    sections: list[str] = []
    for c in keep:
        sec = _top(c["section_path"], c["role"])
        sid = f"sec:{sec}"
        if sid not in g:
            sections.append(sec)
            g.add_node(sid, kind="section", label=sec, order=len(sections))
            g.add_edge("doc", sid, kind="has_section")
    # @self pages are the top-level sections in order (internal.build_self_doc)
    self_pages = conn.execute(
        "SELECT p.page_index, p.page_label FROM source_pages p JOIN references_catalog r"
        " ON r.text_sha256 = p.text_sha256 WHERE r.bib_key = '@self'"
    ).fetchall()
    for p in self_pages:
        section_pages[p["page_index"]] = p["page_label"] or ""

    for c in keep:
        cid = f"claim:{c['claim_pk']}"
        rows = by_claim[c["claim_pk"]]
        verdicts = [r["verdict"] for r in rows if r["verdict"]]
        g.add_node(
            cid, kind="claim", label=c["text_norm"][:90], text=c["text_norm"],
            origin=c["origin"], role=c["role"], file=c["file_path"], line=c["line_start"],
            section=c["section_path"] or "", verdict=_worst(verdicts),
        )  # fmt: skip
        g.add_edge(f"sec:{_top(c['section_path'], c['role'])}", cid, kind="in_section")
        for r in rows:
            if r["bib_key"] == "@self":
                for q in json.loads(r["evidence_json"] or "[]"):
                    label = section_pages.get(q.get("page") or 0)
                    if label and f"sec:{label}" in g:
                        g.add_edge(
                            cid, f"sec:{label}", kind="evidence", verdict=r["verdict"],
                            quote=(q.get("text") or "")[:200],
                        )  # fmt: skip
                continue
            wid = f"work:{r['bib_key']}"
            if wid not in g:
                w = works.get(r["bib_key"])
                g.add_node(
                    wid, kind="work", label=(w["title"] if w and w["title"] else r["bib_key"]),
                    bib_key=r["bib_key"], year=w["year"] if w else None,
                    status=w["source_status"] if w else "MISSING_BIB_ENTRY",
                    provider=w["source_provider"] if w else None,
                )  # fmt: skip
            g.add_edge(cid, wid, kind="cites", verdict=r["verdict"] or "PENDING")
        for e in entities.get(c["claim_hash"], []):
            eid = f"ent:{e['type']}:{norm_name(e['name'])}"
            if eid not in g:
                g.add_node(eid, kind="entity", label=e["name"], etype=e["type"])
            g.add_edge(cid, eid, kind="mentions")
            for r in rows:
                if r["bib_key"] != "@self":
                    g.add_edge(f"work:{r['bib_key']}", eid, kind="about")

    # Drop entities mentioned once with no other connection (noise), keep results/datasets
    for n, d in list(g.nodes(data=True)):
        if (
            d["kind"] == "entity"
            and g.in_degree(n) <= 1
            and d["etype"] not in ("result", "dataset", "method")
        ):
            g.remove_node(n)

    simple = nx.Graph(g.to_undirected())
    pr = pagerank(simple)
    communities: dict[str, int] = {}
    try:
        from networkx.algorithms.community import greedy_modularity_communities

        for i, comm in enumerate(greedy_modularity_communities(simple)):
            for n in comm:
                communities[n] = i
    except Exception:  # noqa: BLE001 - tiny or edgeless graphs
        pass

    nodes = []
    for n, d in g.nodes(data=True):
        nodes.append({
            "id": n, **d, "degree": simple.degree(n) if n in simple else 0,
            "pagerank": round(pr.get(n, 0.0), 6), "community": communities.get(n, 0),
        })  # fmt: skip
    edges = [
        {"id": f"e{i}", "source": u, "target": v, **d}
        for i, (u, v, d) in enumerate(g.edges(data=True))
    ]
    kinds = Counter(d["kind"] for _, d in g.nodes(data=True))
    ents = sorted((x for x in nodes if x["kind"] == "entity"), key=lambda x: -x["pagerank"])[:15]
    return {
        "version": GRAPH_VERSION,
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "counts": dict(kinds), "edges": len(edges), "extraction_cost": round(cost, 6),
            "top_entities": [{"id": e["id"], "label": e["label"], "etype": e["etype"]}
                             for e in ents],
            "sections": sections,
        },
    }  # fmt: skip


def pagerank(g, alpha: float = 0.85, iters: int = 60) -> dict:
    """Pure-Python PageRank on an undirected graph (networkx's needs scipy)."""
    n = g.number_of_nodes()
    if not n:
        return {}
    rank = dict.fromkeys(g, 1.0 / n)
    for _ in range(iters):
        dangling = sum(rank[v] for v in g if g.degree(v) == 0)
        new = {}
        for v in g:
            s = sum(rank[u] / g.degree(u) for u in g.neighbors(v))
            new[v] = (1 - alpha) / n + alpha * (s + dangling / n)
        rank = new
    return rank


_ORDER = ["CONTRADICTED", "NOT_FOUND", "PARTIALLY_SUPPORTED", "UNCHECKABLE", "SUPPORTED"]


def _worst(verdicts: list[str]) -> str | None:
    for v in _ORDER:
        if v in verdicts:
            return v
    return None


def build_graph_for(folder: Path, settings=None, verifier=None) -> dict:
    from texclaim.db.state_store import open_db

    conn = open_db(folder)
    try:
        title = folder.name
        g = build_graph(conn, verifier, title)
    finally:
        conn.close()
    p = graph_path(folder)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    return g


def load_graph(folder: Path) -> dict | None:
    p = graph_path(folder)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
