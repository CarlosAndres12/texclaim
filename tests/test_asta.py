import asyncio
import json

from texclaim.sources.asta_client import AstaClient, asta_refs, parse_sse_result


def _sse(result: dict) -> str:
    return (
        ": ping\n\nevent: message\ndata: "
        + json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})
        + "\n\n"
    )


def test_parse_structured_and_text():
    paper = {"title": "T", "externalIds": {"ArXiv": "1706.03762"}}
    assert parse_sse_result(_sse({"structuredContent": {"result": [paper]}, "content": []})) == [
        paper
    ]
    assert (
        parse_sse_result(_sse({"content": [{"type": "text", "text": json.dumps(paper)}]})) == paper
    )
    assert parse_sse_result(_sse({"isError": True, "content": []})) is None
    assert parse_sse_result("garbage") is None


def test_batch_matches_by_external_id(tmp_path, monkeypatch):
    c = AstaClient("k", tmp_path)
    found = {"title": "Attention", "externalIds": {"ArXiv": "1706.03762", "DOI": "10.1/X"}}

    async def fake_call(tool, args):
        assert tool == "get_paper_batch"
        return [found]  # the unknown id is dropped by the service

    monkeypatch.setattr(c, "_call", fake_call)
    got = asyncio.run(c.papers(["DOI:10.9/missing", "ARXIV:1706.03762"]))
    assert got["ARXIV:1706.03762"]["title"] == "Attention"
    assert got["DOI:10.9/missing"] is None
    # cached: no further calls
    monkeypatch.setattr(c, "_call", None)
    assert asyncio.run(c.papers(["ARXIV:1706.03762"]))["ARXIV:1706.03762"]["title"] == "Attention"


def test_refs():
    class E:
        doi, arxiv_id = "10.1/x", None

    assert asta_refs(E(), None) == ["DOI:10.1/x"]
