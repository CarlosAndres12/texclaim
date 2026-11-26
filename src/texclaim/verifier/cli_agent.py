"""Use a logged-in coding-agent CLI (Claude Code, pi, Antigravity) as the model: no API key.

Model strings: ``cli:claude``, ``cli:claude/haiku``, ``cli:pi``,
``cli:pi/anthropic/claude-haiku-5-5``, ``cli:agy``, ``cli:agy/gemini-4-carbon-low``.
The part after the first ``/`` is passed to the CLI's ``--model`` flag.

Each call runs the CLI once in print mode, in an empty temporary directory, with tools disabled
where the CLI allows it (Claude Code, pi). Antigravity cannot disable tools, so it runs sandboxed
in plan mode; prompts contain third-party source text, so prefer claude or pi.

Costs are recorded as 0: these CLIs bill the user's subscription, not per call.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from texclaim.verifier.llm_client import ProviderError, VerifierCall, VerifyRequest, parse_output

AGENTS = ("claude", "pi", "agy")
ARG_LIMIT = 100_000  # Linux caps a single argument at 128 KiB
KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def parse_model(model: str) -> tuple[str, str | None]:
    """'cli:claude/haiku' -> ('claude', 'haiku')."""
    rest = model.split(":", 1)[1] if ":" in model else model
    agent, _, sub = rest.partition("/")
    if agent not in AGENTS:
        raise ValueError(f"unknown CLI agent '{agent}'; use one of: {', '.join(AGENTS)}")
    return agent, sub or None


def available_agents() -> list[str]:
    return [a for a in AGENTS if shutil.which(a)]


def is_cli_model(model: str | None) -> bool:
    return bool(model) and model.startswith("cli:")


@dataclass
class AgentRun:
    text: str
    raw: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class CliAgentVerifier:
    model: str
    timeout: float = 600.0
    keep_keys: bool = field(default_factory=lambda: bool(os.environ.get("TEXCLAIM_CLI_KEEP_KEYS")))
    supports_schema = False  # the JSON schema goes into the prompt
    is_anthropic = False

    def __post_init__(self) -> None:
        self.agent, self.sub_model = parse_model(self.model)
        self.exe = shutil.which(self.agent)
        if not self.exe:
            raise ProviderError(f"'{self.agent}' is not installed or not on PATH")

    def context_window(self) -> int | None:
        return None

    def estimate_cost(self, _unit=None) -> float:
        return 0.0

    # ---- one CLI call -------------------------------------------------------------------
    def _command(self, system: str, prompt: str, workdir: Path) -> tuple[list[str], bytes | None]:
        exe = self.exe
        assert exe
        if self.agent == "claude":
            cmd = [exe, "-p", "--output-format", "json", "--tools", "",
                   "--no-session-persistence", "--system-prompt", system]  # fmt: skip
            if self.sub_model:
                cmd += ["--model", self.sub_model]
            return cmd, prompt.encode()
        if self.agent == "pi":
            cmd = [exe, "-p", "--mode", "json", "--no-tools", "--no-session", "--no-context-files",
                   "--no-skills", "--no-extensions", "--no-prompt-templates", "--offline",
                   "--system-prompt", system]  # fmt: skip
            if self.sub_model:
                cmd += ["--model", self.sub_model]
            return cmd, prompt.encode()
        # agy: no stdin prompt and no way to disable tools; long prompts go through a file
        full = f"{system}\n\n{prompt}"
        if len(full.encode()) > ARG_LIMIT:
            (workdir / "prompt.md").write_text(full, encoding="utf-8")
            full = (
                "Read the file prompt.md in the current directory. It contains your instructions "
                "and the data. Follow its instructions exactly and reply only with what it asks "
                "for. Do not modify any file and do not run commands."
            )
        cmd = [exe, "--output-format", "json", "--sandbox", "--mode", "plan",
               "--print-timeout", f"{int(self.timeout)}s"]  # fmt: skip
        if self.sub_model:
            cmd += ["--model", self.sub_model]
        cmd += ["-p", full]
        return cmd, None

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.agent == "claude" and not self.keep_keys:
            for k in KEY_VARS:  # use the CLI's own login, not texclaim's API key
                env.pop(k, None)
        return env

    async def run(self, system: str, prompt: str) -> AgentRun:
        with tempfile.TemporaryDirectory(prefix="texclaim-agent-") as tmp:
            workdir = Path(tmp)
            cmd, stdin = self._command(system, prompt, workdir)
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=workdir, env=self._env(),
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )  # fmt: skip
            try:
                out, err = await asyncio.wait_for(proc.communicate(stdin), self.timeout + 30)
            except TimeoutError as e:
                proc.kill()
                await proc.wait()
                raise ProviderError(f"{self.agent} timed out after {int(self.timeout)} s") from e
        stdout = out.decode("utf-8", "replace")
        stderr = err.decode("utf-8", "replace").strip()
        try:
            return parse_agent_output(self.agent, stdout)
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001
            detail = stderr[-300:] or stdout[-300:] or f"exit code {proc.returncode}"
            raise ProviderError(f"{self.agent} failed: {detail}") from e

    # ---- verifier protocol ---------------------------------------------------------------
    async def verify(self, request: VerifyRequest) -> VerifierCall:
        system, user = split_messages(request.messages)
        res = await self.run(system, user)
        call = VerifierCall(None, res.text, res.input_tokens, res.output_tokens, 0.0)
        try:
            call.output = parse_output(res.text)
        except ValueError as e:
            call.error = f"invalid JSON for the schema: {str(e)[:200]}"
        return call

    async def translate(self, text: str, language: str) -> str:
        from texclaim.verifier.prompts import TRANSLATE_SYSTEM

        res = await self.run(TRANSLATE_SYSTEM.format(language=language), text)
        return res.text.strip()

    async def screen(self, texts: list[str]) -> tuple[set[int] | None, float | None]:
        from texclaim.internal import parse_screen, screen_messages

        system, user = split_messages(screen_messages(texts))
        try:
            res = await self.run(system, user)
        except ProviderError:
            return None, None
        return parse_screen(res.text, len(texts)), 0.0

    async def extract_entities(self, items: list[tuple[str, str]]):
        from texclaim.graph.entities import entity_messages, parse_entities

        system, user = split_messages(entity_messages(items))
        try:
            res = await self.run(system, user)
        except ProviderError:
            return None, None
        return parse_entities(res.text, items), 0.0


def split_messages(messages: list[dict]) -> tuple[str, str]:
    def text(c) -> str:
        return c if isinstance(c, str) else "\n".join(p["text"] for p in c)

    system = "\n\n".join(text(m["content"]) for m in messages if m["role"] == "system")
    user = "\n\n".join(text(m["content"]) for m in messages if m["role"] != "system")
    return system, user


def parse_agent_output(agent: str, stdout: str) -> AgentRun:
    """The assistant's final text from each CLI's JSON output."""
    if agent == "claude":
        d = json.loads(stdout.strip().splitlines()[-1])
        if d.get("is_error") or d.get("subtype", "success") != "success":
            raise ProviderError(f"claude: {str(d.get('result') or d.get('subtype'))[:300]}")
        u = d.get("usage") or {}
        tokens_in = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                "cache_read_input_tokens"))  # fmt: skip
        return AgentRun(d.get("result") or "", stdout, tokens_in, u.get("output_tokens"))
    if agent == "pi":
        final = None
        for line in stdout.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            msg = ev.get("message") or {}
            if ev.get("type") == "message_end" and msg.get("role") == "assistant":
                final = msg
        if final is None:
            raise ValueError("no assistant message in pi output")
        if final.get("stopReason") == "error":
            raise ProviderError(f"pi: {str(final.get('errorMessage'))[:300]}")
        text = "".join(
            p.get("text", "") for p in final.get("content", []) if p.get("type") == "text"
        )
        usage = final.get("usage") or {}
        return AgentRun(text, stdout, usage.get("input"), usage.get("output"))
    # agy
    d = json.loads(stdout.strip().splitlines()[-1])
    if d.get("status") != "SUCCESS":
        raise ProviderError(f"agy: {str(d.get('error') or d.get('status'))[:300]}")
    u = d.get("usage") or {}
    return AgentRun(d.get("response") or "", stdout, u.get("input_tokens"), u.get("output_tokens"))
