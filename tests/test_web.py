import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from texclaim.graph.mcp_server import GraphTools, handle
from texclaim.web.app import create_app
from texclaim.web.projects import ProjectError, ProjectStore, safe_relpath

TEX = r"""\documentclass{article}
\begin{document}
\begin{abstract}
We show that our model improves accuracy by 12 points over the baseline.
\end{abstract}
\section{Introduction}
Transformers reach 28.4 BLEU on translation \cite{vaswani}. Residual networks are deep \cite{he}.
\section{Results}
Our model reaches 85\% accuracy while the baseline reaches 80\% on the test set.
\section{Conclusions}
Our model improves accuracy by 12 points, which is a large gain overall.
\end{document}
"""
BIB = """@article{vaswani, title={Attention is all you need}, author={Vaswani, Ashish}, year={2017}}
@article{he, title={Deep residual learning}, author={He, Kaiming}, year={2016}}
"""


@pytest.fixture
def client(tmp_path):
    store = ProjectStore(tmp_path / "data")
    with TestClient(create_app(store)) as c:
        yield c


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("paper/main.tex", TEX)
        z.writestr("paper/refs.bib", BIB)
        z.writestr("paper/../evil.tex", "x")
        z.writestr("__MACOSX/._main.tex", "x")
    return buf.getvalue()


def _wait(client, pid, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(f"/api/projects/{pid}/runs/current").json()
        if r["state"] != "running":
            return r
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def test_health(client):
    h = client.get("/api/health").json()
    assert "keys" in h and "demo" in h["suggested_models"]
    assert all(isinstance(v, bool) for v in h["keys"].values())


def test_full_flow(client):
    r = client.post("/api/projects", files={"files": ("paper.zip", _zip(), "application/zip")})
    assert r.status_code == 200, r.text
    p = r.json()
    assert sorted(p["files"]) == ["main.tex", "refs.bib"]
    assert p["name"] == "main"
    pid = p["id"]

    out = client.get(f"/api/projects/{pid}/outline").json()
    assert out["kind"] == "latex" and out["cited_claims"] == 2
    assert [s["title"] for s in out["sections"]] == [
        "Abstract", "Introduction", "Results", "Conclusions"
    ]  # fmt: skip

    s = client.put(
        f"/api/projects/{pid}/settings",
        json={"model": "demo", "offline": True, "claim_scope": "two", "bogus": 1},
    ).json()
    assert s["model"] == "demo" and s["claim_scope"] == "two"
    bad = client.put(f"/api/projects/{pid}/settings", json={"claim_scope": "huge"})
    assert bad.status_code == 400

    assert client.post(f"/api/projects/{pid}/runs", json={}).status_code == 200
    final = _wait(client, pid)
    assert final["state"] == "done", final
    types = [e["type"] for e in final["log"]]
    assert "plan" in types and "done" in types and "unit" in types

    # SSE replays the finished job's log, then ends
    body = client.get(f"/api/projects/{pid}/events").text
    assert '"type": "done"' in body and "event: end" in body

    rep = client.get(f"/api/projects/{pid}/report").json()
    assert rep["units"]
    assert {u["bib_key"] for u in rep["units"]} >= {"vaswani", "he"}
    proj = client.get(f"/api/projects/{pid}").json()
    assert proj["summary"]["units"] == len(rep["units"])
    assert proj["has_graph"]

    for fmt in ("md", "json", "html", "docx"):
        d = client.get(f"/api/projects/{pid}/report.{fmt}")
        assert d.status_code == 200, (fmt, d.text[:200])
        assert "attachment" in d.headers["content-disposition"]

    g = client.get(f"/api/projects/{pid}/graph").json()
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"document", "section", "claim", "work"} <= kinds

    doc = client.get(f"/api/projects/{pid}/document").json()
    assert doc["files"][0]["path"] == "main.tex"

    src = client.get(f"/api/projects/{pid}/sources").json()
    assert {s["bib_key"] for s in src} == {"vaswani", "he"}
    assert all(s["file_kind"] == "none" for s in src)  # offline, no PDFs
    assert client.get(f"/api/projects/{pid}/sources/he/file").status_code == 404
    fake = client.post(
        f"/api/projects/{pid}/sources/he/pdf",
        files={"file": ("x.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert fake.status_code == 400  # unreadable PDFs are rejected at upload
    from fixtures.make_pdfs import make_pdf

    pdf = make_pdf(["Deep residual learning for image recognition. " * 12])
    up = client.post(
        f"/api/projects/{pid}/sources/he/pdf", files={"file": ("x.pdf", pdf, "application/pdf")}
    )
    assert up.json()["saved"] == "papers/he.pdf"
    notpdf = client.post(
        f"/api/projects/{pid}/sources/he/pdf", files={"file": ("x.pdf", b"hello", "text/plain")}
    )
    assert notpdf.status_code == 400
    z = client.get(f"/api/projects/{pid}/sources.zip")
    assert z.status_code == 200 and z.content[:2] == b"PK"

    raw = client.get(f"/api/projects/{pid}/files/raw", params={"path": "papers/he.pdf"})
    assert raw.status_code == 200 and raw.headers["content-type"] == "application/pdf"
    assert client.get(
        f"/api/projects/{pid}/files/raw", params={"path": "../project.json"}
    ).status_code == 400  # fmt: skip

    assert client.delete(f"/api/projects/{pid}").json() == {"ok": True}
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_markdown_project_and_failure(client):
    md = "# Intro\n\nTransformers are good [@a].\n"
    r = client.post(
        "/api/projects",
        data={"name": "MD"},
        files=[("files", ("paper.md", md, "text/markdown")),
               ("files", ("refs.bib", "@article{a, title={A}, year={2017}}", "text/plain"))],
    )  # fmt: skip
    pid = r.json()["id"]
    assert client.get(f"/api/projects/{pid}/outline").json()["kind"] == "markdown"
    # No model configured: the run fails cleanly with a message
    client.post(f"/api/projects/{pid}/runs", json={})
    final = _wait(client, pid)
    assert final["state"] == "failed" and "model" in final["error"].lower()


def test_rejects_bad_uploads(client):
    r = client.post("/api/projects", files={"files": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400
    assert client.post("/api/projects").status_code == 400
    assert client.get("/api/projects/zzzzzzzzzzzz").status_code == 404


def test_safe_relpath():
    assert safe_relpath("a/b.tex").as_posix() == "a/b.tex"
    for bad in ("../x", "a/../../x", ".texclaim/state.db", ""):
        with pytest.raises(ProjectError):
            safe_relpath(bad)


def test_spa_fallback(client):
    r = client.get("/projects/abc")
    assert r.status_code == 200 and "<" in r.text
    assert client.get("/api/nothing").status_code == 404


def test_mcp_tools(client, tmp_path):
    r = client.post("/api/projects", files={"files": ("paper.zip", _zip(), "application/zip")})
    pid = r.json()["id"]
    client.put(f"/api/projects/{pid}/settings", json={"model": "demo", "offline": True})
    client.post(f"/api/projects/{pid}/runs", json={})
    _wait(client, pid)
    folder = client.app.state.store.get(pid).path
    tools = GraphTools(folder)
    init = handle(tools, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init["result"]["serverInfo"]["name"] == "texclaim"
    names = [t["name"] for t in handle(tools, {"id": 2, "method": "tools/list"})["result"]["tools"]]
    assert names == ["graph_search", "graph_neighbors", "claim_detail", "findings"]
    res = handle(
        tools,
        {
            "id": 3,
            "method": "tools/call",
            "params": {"name": "graph_search", "arguments": {"query": "accuracy"}},
        },
    )
    hits = json.loads(res["result"]["content"][0]["text"])
    assert hits and any(h["kind"] == "claim" for h in hits)
    claim = next(h for h in hits if h["kind"] == "claim")
    nb = handle(
        tools,
        {
            "id": 4,
            "method": "tools/call",
            "params": {"name": "graph_neighbors", "arguments": {"id": claim["id"]}},
        },
    )
    assert json.loads(nb["result"]["content"][0]["text"])["edges"]
    det = handle(
        tools,
        {
            "id": 5,
            "method": "tools/call",
            "params": {"name": "claim_detail", "arguments": {"id": claim["id"]}},
        },
    )
    assert "results" in json.loads(det["result"]["content"][0]["text"])
    err = handle(
        tools,
        {
            "id": 6,
            "method": "tools/call",
            "params": {"name": "graph_neighbors", "arguments": {"id": "nope"}},
        },
    )
    assert err["result"]["isError"]
    assert handle(tools, {"method": "notifications/initialized"}) is None


def test_upload_without_manuscript_is_rejected(client):
    r = client.post("/api/projects", files={"files": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400 and "No manuscript" in r.json()["detail"]
    assert client.get("/api/projects").json() == []


def test_word_project_survives_second_run(client):
    from pathlib import Path

    docx = Path(__file__).parents[1] / "examples" / "word" / "paper.docx"
    pid = client.post(
        "/api/projects",
        files={"files": ("paper.docx", docx.read_bytes(), "application/octet-stream")},
    ).json()["id"]
    client.put(f"/api/projects/{pid}/settings", json={"model": "demo", "offline": True})
    for _ in range(2):
        client.post(f"/api/projects/{pid}/runs", json={})
        assert _wait(client, pid)["state"] == "done"
    out = client.get(f"/api/projects/{pid}/outline").json()
    assert out["main"] == "paper.docx"
    assert {s["title"] for s in out["sections"]} >= {"Introduction", "Results", "Conclusions"}


def test_corrupt_docx_rejected(client):
    r = client.post(
        "/api/projects", files={"files": ("broken.docx", b"PK\x03\x04garbage", "application/zip")}
    )
    assert r.status_code == 400 and "damaged" in r.json()["detail"]
