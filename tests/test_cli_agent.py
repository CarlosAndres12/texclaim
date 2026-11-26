import json
import shutil

import pytest

from texclaim.verifier import cli_agent
from texclaim.verifier.cli_agent import (
    CliAgentVerifier,
    parse_agent_output,
    parse_model,
    split_messages,
)
from texclaim.verifier.llm_client import ProviderError


def test_parse_model():
    assert parse_model("cli:claude") == ("claude", None)
    assert parse_model("cli:claude/haiku") == ("claude", "haiku")
    assert parse_model("cli:pi/anthropic/claude-haiku-5-5") == ("pi", "anthropic/claude-haiku-5-5")
    with pytest.raises(ValueError):
        parse_model("cli:nope")


def test_parse_claude_output():
    out = json.dumps({"type": "result", "subtype": "success", "is_error": False,
                      "result": '{"ok": true}', "usage": {"input_tokens": 5,
                      "cache_read_input_tokens": 10, "output_tokens": 3}})  # fmt: skip
    r = parse_agent_output("claude", out)
    assert r.text == '{"ok": true}' and r.input_tokens == 15 and r.output_tokens == 3
    bad = json.dumps({"subtype": "success", "is_error": True, "result": "Not logged in"})
    with pytest.raises(ProviderError, match="Not logged in"):
        parse_agent_output("claude", bad)


def test_parse_pi_output():
    events = [
        {"type": "message_end", "message": {"role": "user", "content": [{"type": "text",
                                                                          "text": "hi"}]}},
        {"type": "message_end", "message": {"role": "assistant", "stopReason": "stop",
         "content": [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": "{\"a\": 1}"}],
         "usage": {"input": 7, "output": 2}}},
        {"type": "agent_end"},
    ]  # fmt: skip
    r = parse_agent_output("pi", "\n".join(json.dumps(e) for e in events))
    assert r.text == '{"a": 1}' and r.input_tokens == 7
    err = {"type": "message_end", "message": {"role": "assistant", "stopReason": "error",
           "content": [], "errorMessage": "credit balance is too low"}}  # fmt: skip
    with pytest.raises(ProviderError, match="credit balance"):
        parse_agent_output("pi", json.dumps(err))


def test_parse_agy_output():
    ok = json.dumps({"status": "SUCCESS", "response": "{}\n", "usage": {"input_tokens": 9}})
    assert parse_agent_output("agy", ok).text == "{}\n"
    with pytest.raises(ProviderError):
        parse_agent_output("agy", json.dumps({"status": "ERROR", "error": "quota"}))


def test_split_messages():
    parts = [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": parts}]
    assert split_messages(msgs) == ("S", "A\nB")


def _fake(monkeypatch, agent):
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    return CliAgentVerifier(f"cli:{agent}/m1")


def test_commands_and_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    v = _fake(monkeypatch, "claude")
    cmd, stdin = v._command("SYS", "PROMPT", tmp_path)
    assert cmd[:2] == ["/usr/bin/claude", "-p"] and "--tools" in cmd and stdin == b"PROMPT"
    assert cmd[cmd.index("--model") + 1] == "m1"
    assert "ANTHROPIC_API_KEY" not in v._env()  # uses the CLI's own login

    p = _fake(monkeypatch, "pi")
    cmd, stdin = p._command("SYS", "PROMPT", tmp_path)
    assert "--no-tools" in cmd and stdin == b"PROMPT"
    assert "ANTHROPIC_API_KEY" in p._env()

    a = _fake(monkeypatch, "agy")
    cmd, stdin = a._command("SYS", "short", tmp_path)
    assert stdin is None and cmd[-2:] == ["-p", "SYS\n\nshort"] and "--sandbox" in cmd
    cmd, _ = a._command("SYS", "x" * (cli_agent.ARG_LIMIT + 10), tmp_path)
    assert "prompt.md" in cmd[-1] and (tmp_path / "prompt.md").stat().st_size > cli_agent.ARG_LIMIT


def test_missing_cli(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ProviderError, match="not installed"):
        CliAgentVerifier("cli:claude")


def test_make_verifier_cli(monkeypatch):
    from texclaim.check import make_verifier
    from texclaim.config import ConfigError, Settings

    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ConfigError, match="not installed"):
        make_verifier(Settings(model="cli:agy"))


async def test_verify_end_to_end_with_fake_cli(monkeypatch, tmp_path):
    """A fake 'claude' script returns a verifier answer; the engine path parses it."""
    from texclaim.models import Unit
    from texclaim.verifier.evidence import Block, Evidence
    from texclaim.verifier.llm_client import VerifyRequest

    answer = {"citation_function": "SUPPORTS_CLAIM", "claim_scope": "s", "quotes": [],
              "analysis": "a", "verdict": "UNCHECKABLE", "reason_code": "OTHER",
              "what_is_wrong": None, "what_source_says": None, "suggested_fix": None,
              "confidence": "low"}  # fmt: skip
    script = tmp_path / "claude"
    payload = json.dumps({"subtype": "success", "is_error": False, "result": json.dumps(answer)})
    script.write_text(f"#!/bin/sh\ncat > /dev/null\necho '{payload}'\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    v = CliAgentVerifier("cli:claude")
    unit = Unit(
        unit_key="k", bib_key="b", claim_hash="h", text_norm="S", context_norm="",
        unit_kind="sentence", section_path="", file_path="f.tex", line_start=1,
        cite_command="", prenote=None, postnote=None, group_keys=["b"], attributed_span="S",
        other_keys=[], source_status="FULL_TEXT", text_sha256="x", source_language=None,
        source_provider=None, source_version=None, strategy="full",
    )  # fmt: skip
    ev = Evidence("full", "full_text", [Block("P1", "[[P1]]", "text", 1, None, [(0, 4, 0)])])
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "claim"}]
    call = await v.verify(VerifyRequest(unit, ev, msgs))
    assert call.output is not None and call.output.verdict == "UNCHECKABLE"
    assert call.cost_usd == 0.0
