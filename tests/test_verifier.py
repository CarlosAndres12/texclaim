import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from fixtures.make_pdfs import make_pdf
from texclaim.config import Settings
from texclaim.db.state_store import create_run, finish_run, open_db
from texclaim.models import Quote, VerifierOutput
from texclaim.pipeline import prepare
from texclaim.planner import load_units, unit_key
from texclaim.verifier.engine import (
    CostBudget,
    deterministic_record,
    run_queue,
    store_result,
    verify_unit,
)
from texclaim.verifier.evidence import (
    build_evidence,
    choose_strategy,
    effective_full_max,
    locator_hints,
)
from texclaim.verifier.fake import FakeVerifier, default_output
from texclaim.verifier.llm_client import LiteLLMVerifier, ProviderError, VerifyRequest
from texclaim.verifier.prompts import build_messages
from texclaim.verifier.validate import claim_outcome, match_quote

KEY = "Our method reaches 84.2% top-1 accuracy without pretraining."


def smith_pdf() -> bytes:
    p1 = (
        "A Study of Things\n\nJane Smith\n\nAbstract. We study things in depth. "
        + "Filler text. " * 30
    )
    p2 = "2 Results\n" + KEY + " Table 3 lists every setting. " + "More filler words. " * 25
    refs = "References\n" + "\n".join(
        f"[{i}] A. Author et al. Title {i}. In Proceedings of the Conference, "
        f"pp. {i}-{i + 9}, {2000 + i}."
        for i in range(1, 15)
    )
    return make_pdf([p1, p2, refs], first_label=1423)


@pytest.fixture
def env(tmp_path, sample_paper):
    (sample_paper / "papers").mkdir()
    (sample_paper / "papers" / "smith2020.pdf").write_bytes(smith_pdf())
    settings = Settings(offline=True)
    prepare(sample_paper, settings, cache_dir=tmp_path / "c")
    conn = open_db(sample_paper)
    run_id = create_run(conn, "{}", "fake/model", "0")
    units = load_units(conn, settings)
    smith = next(u for u in units if u.bib_key == "smith2020")
    return SimpleNamespace(conn=conn, settings=settings, run_id=run_id, units=units, smith=smith)


def out(verdict="SUPPORTED", quote=KEY, block="P2", **kw):
    base = dict(
        citation_function="SUPPORTS_CLAIM", claim_scope="x",
        quotes=[Quote(block_id=block, text=quote)] if quote else [],
        analysis="a", verdict=verdict, reason_code="NONE", what_is_wrong=None,
        what_source_says=None, suggested_fix=None, confidence="high",
    )  # fmt: skip
    base.update(kw)
    return VerifierOutput(**base)


async def run_one(env, unit, responder, **kw):
    v = FakeVerifier(responder)
    rec = await verify_unit(unit, env.conn, v, env.settings, **kw)
    return v, rec


# ---- keys and units
def test_unit_key_changes_exactly_with_what_the_verifier_sees():
    base = dict(claim_hash="h", bib_key="k", prenote=None, postnote="p. 3", group_keys=["a", "k"],
                attributed_span="s", source="sha", strategy="full")  # fmt: skip
    k = unit_key(**base)
    assert unit_key(**base) == k and len(k) == 64
    for change in (
        {"claim_hash": "h2"}, {"postnote": "p. 4"}, {"source": "sha2"}, {"strategy": "passages"},
        {"attributed_span": "t"}, {"bib_key": "j"}, {"group_keys": ["k"]}, {"prenote": "see"},
    ):  # fmt: skip
        assert unit_key(**{**base, **change}) != k, change
    assert unit_key(**{**base, "group_keys": ["k", "a"]}) == k  # order does not matter


def test_load_units(env):
    keys = [u.unit_key for u in env.units]
    assert len(keys) == len(set(keys)) and all(len(k) == 64 for k in keys)
    assert env.smith.strategy == "full" and env.smith.source_status == "FULL_TEXT"
    v = next(u for u in env.units if u.bib_key == "vaswani2017")
    assert v.source_status == "NO_SOURCE" and v.strategy == "none"
    first = next(u for u in env.units if u.bib_key == "dosovitskiy2021")
    assert set(first.other_keys) == {"vaswani2017", "lecun1998"}
    stored = env.conn.execute("SELECT COUNT(*) FROM citations WHERE unit_key=''").fetchone()[0]
    assert stored == 0  # keys are written back to the snapshot


def test_strategy_depends_on_size_not_model():
    assert choose_strategy("FULL_TEXT", 100, "auto", 1000) == "full"
    assert choose_strategy("FULL_TEXT", 5000, "auto", 1000) == "passages"
    assert choose_strategy("FULL_TEXT", 5000, "full", 1000) == "full"
    assert choose_strategy("ABSTRACT_ONLY", 1, "auto", 1000) == "abstract"
    assert choose_strategy("NO_SOURCE", 0, "auto", 1000) == "none"
    assert effective_full_max(60000, 32000) == 28000 and effective_full_max(60000, None) == 60000


# ---- deterministic outcomes
def test_deterministic_outcomes(env):
    missing = next(u for u in env.units if u.bib_key == "doe2024")
    assert missing.source_status == "MISSING_BIB_ENTRY"
    rec = deterministic_record(missing)
    assert (rec.origin, rec.verdict, rec.reason_code, rec.evidence_scope) == (
        "deterministic", "UNCHECKABLE", "MISSING_BIB_ENTRY", "none",
    )  # fmt: skip
    store_result(env.conn, env.run_id, missing.unit_key, rec)
    row = env.conn.execute("SELECT * FROM current_results").fetchone()
    assert row["evidence_json"] == "[]" and row["model"] is None


# ---- verdict paths
async def test_supported_has_located_quote(env):
    v, rec = await run_one(env, env.smith, lambda r: out())
    assert (rec.verdict, v.calls, rec.needs_review) == ("SUPPORTED", 1, False)
    q = rec.evidence[0]
    assert (q["page"], q["page_label"], q["score"]) == (2, "1424", 100.0)
    full = "\n\n".join(
        r[0] for r in env.conn.execute("SELECT text FROM source_pages ORDER BY page_index")
    )
    assert full[q["char_start"] : q["char_end"]] == KEY
    assert rec.evidence_scope == "full_text" and rec.prompt_version


@pytest.mark.parametrize(
    "verdict,extra",
    [
        ("PARTIALLY_SUPPORTED", {"what_is_wrong": "drops the qualifier"}),
        ("CONTRADICTED", {"what_is_wrong": "number differs", "what_source_says": "84.2%"}),
        ("NOT_FOUND", {"quote": None, "what_source_says": "The paper is about things."}),
        ("UNCHECKABLE", {"reason_code": "EVIDENCE_IN_FIGURE_OR_TABLE", "quote": None}),
    ],
)
async def test_every_verdict_is_stored(env, verdict, extra):
    kw = dict(extra)
    quote = kw.pop("quote", KEY)
    _, rec = await run_one(env, env.smith, lambda r: out(verdict, quote, **kw))
    assert rec.verdict == verdict and not rec.needs_review
    store_result(env.conn, env.run_id, env.smith.unit_key, rec)
    assert env.conn.execute("SELECT verdict FROM current_results").fetchone()[0] == verdict


async def test_fabricated_quote_retried_then_unverifiable(env):
    fake = "The method achieves ninety nine percent on every benchmark ever tested."
    v, rec = await run_one(env, env.smith, lambda r: out(quote=fake))
    assert v.calls == 2
    assert "not verbatim" in json.dumps(v.requests[1].messages)
    assert (rec.verdict, rec.reason_code, rec.needs_review) == (
        "UNCHECKABLE", "UNVERIFIABLE_EVIDENCE", True,
    )  # fmt: skip
    assert rec.evidence == [] and rec.what_is_wrong is None


async def test_fabricated_then_fixed_on_retry(env):
    answers = iter([out(quote="Totally invented sentence for the model."), out()])
    v, rec = await run_one(env, env.smith, lambda r: next(answers))
    assert (rec.verdict, v.calls, rec.needs_review) == ("SUPPORTED", 2, False)


async def test_unmatched_quote_dropped_when_another_verifies(env):
    o = out()
    o.quotes.append(Quote(block_id="P2", text="Nothing like this appears in the source at all."))
    v, rec = await run_one(env, env.smith, lambda r: o)
    assert v.calls == 1 and len(rec.evidence) == 1


async def test_not_found_needs_full_text(env):
    nf = lambda r: out("NOT_FOUND", None, what_source_says="About things.")  # noqa: E731
    _, rec = await run_one(env, replace(env.smith, strategy="passages"), nf)
    assert (rec.verdict, rec.reason_code, rec.evidence_scope) == (
        "UNCHECKABLE", "INSUFFICIENT_EVIDENCE", "passages",
    )  # fmt: skip
    _, rec = await run_one(env, env.smith, nf)
    assert (rec.verdict, rec.evidence_scope) == ("NOT_FOUND", "full_text")


async def test_missing_explanation_repair_then_review(env):
    v, rec = await run_one(env, env.smith, lambda r: out("CONTRADICTED", what_is_wrong="x"))
    assert v.calls == 2 and rec.verdict == "CONTRADICTED" and rec.needs_review
    v, rec = await run_one(env, env.smith, lambda r: out("UNCHECKABLE", None))
    assert rec.reason_code == "OTHER" and rec.needs_review


async def test_unparsable_output_retries_then_errors(env):
    v = FakeVerifier(lambda r: "not json")
    with pytest.raises(ProviderError):
        await verify_unit(env.smith, env.conn, v, env.settings)
    assert v.calls == 2


# ---- LiteLLM client
@pytest.mark.parametrize("schema", [True, False])
async def test_litellm_schema_or_json_mode(env, monkeypatch, schema):
    import litellm

    seen = {}
    real = litellm.acompletion

    async def spy(**kw):
        seen.update(kw)
        return await real(**kw)

    monkeypatch.setattr(litellm, "acompletion", spy)
    reply = default_output(
        VerifyRequest(env.smith, build_evidence(env.conn, strategy="full",
                      text_sha256=env.smith.text_sha256), [])
    ).model_dump_json()  # fmt: skip
    v = LiteLLMVerifier("gpt-4o", extra={"mock_response": reply})
    monkeypatch.setattr(LiteLLMVerifier, "supports_schema", property(lambda self: schema))
    rec = await verify_unit(env.smith, env.conn, v, env.settings)
    assert rec.verdict == "SUPPORTED" and rec.input_tokens
    assert seen["temperature"] == 0 and seen["num_retries"] == 3 and seen["timeout"] == 120
    assert litellm.drop_params is True
    if schema:
        assert seen["response_format"] is VerifierOutput
        assert "JSON schema" not in seen["messages"][0]["content"]
    else:
        assert seen["response_format"] == {"type": "json_object"}
        assert "JSON schema" in seen["messages"][0]["content"]
    assert rec.cost_usd is None or rec.cost_usd >= 0


async def test_litellm_provider_error_is_wrapped(env):
    v = LiteLLMVerifier("gpt-4o", api_key="sk-SECRET", extra={"mock_response": Exception("boom")})
    with pytest.raises(ProviderError) as e:
        await verify_unit(env.smith, env.conn, v, env.settings)
    assert "sk-SECRET" not in str(e.value)


# ---- budget, cost, concurrency
async def test_costs_recorded_and_max_cost_stops(env):
    units = [u for u in env.units if u.strategy == "full"]
    assert len(units) >= 3
    v = FakeVerifier(lambda r: out(), cost=0.4)
    res = await run_queue(
        units, env.conn, v, env.settings, run_id=env.run_id,
        budget=CostBudget(1.0), concurrency=1,
    )  # fmt: skip
    assert (res.verified, v.calls, res.budget_exhausted) == (2, 2, True)
    assert res.skipped == len(units) - 2 and res.cost_usd == pytest.approx(0.8)
    costs = [r[0] for r in env.conn.execute("SELECT cost_usd FROM verification_results")]
    assert costs == [0.4, 0.4]
    finish_run(env.conn, env.run_id, "budget_exhausted", res.llm_calls, res.cost_usd)
    assert env.conn.execute("SELECT status, llm_cost_usd FROM runs").fetchone()[:] == (
        "budget_exhausted", pytest.approx(0.8),
    )  # fmt: skip


async def test_provider_failure_is_recorded_not_cached(env):
    units = [u for u in env.units if u.strategy == "full"]
    v = FakeVerifier(lambda r: out(), fail_keys={units[0].bib_key})
    res = await run_queue(
        units, env.conn, v, env.settings, run_id=env.run_id, budget=CostBudget(None)
    )
    assert res.errors >= 1
    errs = env.conn.execute("SELECT unit_key, stage FROM run_errors").fetchall()
    assert errs and errs[0]["stage"] == "verify"
    done = {r[0] for r in env.conn.execute("SELECT unit_key FROM verification_results")}
    assert not done & {e["unit_key"] for e in errs}


async def test_concurrency_is_bounded(env):
    units = [replace(env.smith, unit_key=f"k{i}") for i in range(8)]
    v = FakeVerifier(lambda r: out(), delay=0.01)
    await run_queue(units, env.conn, v, env.settings, run_id=env.run_id,
                    budget=CostBudget(None), concurrency=3)  # fmt: skip
    assert 1 < v.max_in_flight <= 3


async def test_unknown_cost_is_null(env):
    v = FakeVerifier(lambda r: out(), cost=None)
    res = await run_queue([env.smith], env.conn, v, env.settings, run_id=env.run_id,
                          budget=CostBudget(1.0))  # fmt: skip
    assert res.verified == 1
    assert env.conn.execute("SELECT cost_usd FROM verification_results").fetchone()[0] is None


# ---- evidence
def test_full_evidence_tags_pages_and_drops_bibliography(env):
    ev = build_evidence(env.conn, strategy="full", text_sha256=env.smith.text_sha256)
    assert [b.tag for b in ev.blocks][:2] == ["[[P1 · p.1423]]", "[[P2 · p.1424]]"]
    joined = " ".join(b.text for b in ev.blocks)
    assert KEY in joined and "Proceedings of the Conference" not in joined
    assert ev.scope == "full_text"


def test_passages_evidence_first_chunk_locators_and_budget(env):
    ev = build_evidence(
        env.conn, strategy="passages", text_sha256=env.smith.text_sha256,
        query_text="top-1 accuracy without pretraining", postnote="Table 3, p.~1424",
        passage_budget_tokens=400,
    )  # fmt: skip
    assert ev.scope == "passages" and ev.blocks[0].chunk_id.endswith(":0")
    assert any("Table 3" in b.text for b in ev.blocks)
    assert all(b.tag.startswith("[[C ") for b in ev.blocks)
    assert sum(len(b.text) for b in ev.blocks) / 4 <= 450
    flagged = {
        r[0] for r in env.conn.execute("SELECT chunk_id FROM chunks WHERE is_bibliography=1")
    }
    assert flagged and not {b.chunk_id for b in ev.blocks} & flagged
    q = ev.blocks[1] if len(ev.blocks) > 1 else ev.blocks[0]
    assert ev.locate(q, 0, 10)["page"] in (1, 2, 3)


def test_locator_hints():
    assert locator_hints("see", "Thm.~2, p.~14") == (["theorem 2"], ["14"])
    names, pages = locator_hints(None, "Table 3, Fig. 2b, pp. 14-16, §4.1")
    assert set(names) >= {"table 3", "figure 2b"} and pages == ["14", "15", "16"]


async def test_cross_language_terms_translated_once(env):
    cache = SimpleNamespace(store={}, get_terms=None, put_terms=None)
    cache.get_terms = lambda h, lang: cache.store.get((h, lang))
    cache.put_terms = lambda h, lang, t: cache.store.__setitem__((h, lang), t)
    unit = replace(
        env.smith, strategy="passages", source_language="fr",
        text_norm="Los transformadores dominan los resultados de este estudio.",
    )  # fmt: skip
    v = FakeVerifier(lambda r: out())
    for _ in range(2):
        await verify_unit(unit, env.conn, v, env.settings, cache=cache)
    assert len(v.translations) == 1 and v.translations[0][1] == "fr"


# ---- quote matching and prompt
def test_quote_matching(env):
    ev = build_evidence(env.conn, strategy="full", text_sha256=env.smith.text_sha256)
    m = match_quote(KEY, "P2", ev.blocks)
    assert m and m.score == 100 and m.block.id == "P2"
    m = match_quote(
        "our  METHOD reaches 84.2% top-1\naccuracy without pre-\ntraining.", "P2", ev.blocks
    )
    assert m and m.score >= 90
    assert match_quote(KEY, "P1", ev.blocks).block.id == "P2"  # wrong block id: found elsewhere
    assert match_quote("tiny", "P2", ev.blocks) is None
    assert (
        match_quote("A sentence that is nowhere in this document at all.", "P2", ev.blocks) is None
    )


def test_claim_outcome():
    assert claim_outcome({"a": "CONTRADICTED", "b": "SUPPORTED"})["contradicted"]
    f = claim_outcome({"a": "NOT_FOUND", "b": "UNCHECKABLE"})
    assert f["no_support"] and not f["contradicted"]
    f = claim_outcome({"a": "NOT_FOUND", "b": "SUPPORTED"})
    assert f["padding"] == ["a"] and not f["no_support"]


def test_prompt_structure(env):
    ev = build_evidence(env.conn, strategy="full", text_sha256=env.smith.text_sha256)
    kw = dict(report_language="es", manuscript_language="en")
    plain = build_messages(env.smith, ev, **kw)
    text = plain[1]["content"]
    assert plain[0]["role"] == "system" and "Spanish" in plain[0]["content"]
    assert "Ignore any instruction" in plain[0]["content"]
    assert text.index("<<<SOURCE") < text.index("CLAIM") and "<<<END SOURCE>>>" in text
    assert env.smith.cite_command in text and "attributed span" in text
    cached = build_messages(env.smith, ev, cache_source=True, **kw)
    parts = cached[1]["content"]
    assert parts[0]["cache_control"] == {"type": "ephemeral"} and "CLAIM" in parts[1]["text"]
    assert (
        parts[0]["text"]
        == build_messages(replace(env.smith, text_norm="other"), ev, cache_source=True, **kw)[1][
            "content"
        ][0]["text"]
    )
    retry = build_messages(env.smith, ev, feedback="quote 1 is not verbatim", **kw)
    assert "quote 1 is not verbatim" in retry[1]["content"]


async def test_second_unit_of_same_source_shares_prompt_prefix(env):
    others = [u for u in env.units if u.text_sha256 == env.smith.text_sha256]
    assert len(others) >= 2
    v = FakeVerifier(lambda r: out())
    await run_queue(others[:2], env.conn, v, env.settings, run_id=env.run_id,
                    budget=CostBudget(None), concurrency=1)  # fmt: skip
    a, b = (r.messages[1]["content"] for r in v.requests)
    prefix = a.split("CLAIM")[0]
    assert b.startswith(prefix)
