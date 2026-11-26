# texclaim for AI agents

This file tells an AI agent (Claude Code, pi, Antigravity, Codex, …) how to install, configure and
run texclaim for a user. Humans: see `docs/GUIDE.md` (English) or `docs/GUIA.md` (español), or
open the web app's **Help → Setup guide**.

## Ground rules

- **Never print, log or commit secret values.** Read only whether a key is set
  (`texclaim config show --json` or `GET /api/config`). Keys live in a `.env` file with mode 0600.
- **Ask the user before** storing a key they have not given you, choosing a paid model, or running
  a full check (it calls a model once per citation; ~$0.02-0.05 per short paper with a small model).
- Prefer `--dry-run` / `texclaim config test` before a real run.
- Do not edit the user's manuscript; texclaim never modifies `.tex`, `.md`, `.docx` or `.bib` files.

## 1. Check the installation

```bash
texclaim --version
texclaim doctor          # install, keys present (never printed), agent CLIs, model
texclaim config show     # keys set / not set, defaults, available agent CLIs
```

If `texclaim` is missing: `pipx install --editable <texclaim folder>` (or `make install-global`).
Markdown and Word manuscripts need `pandoc`.

## 2. Choose a model (one of three ways)

| Way | Model string | Needs |
| --- | --- | --- |
| Agent CLI already logged in | `cli:claude`, `cli:claude/haiku`, `cli:pi`, `cli:pi/<provider/model>`, `cli:agy`, `cli:agy/<model>` | The CLI installed and logged in; **no API key** |
| Provider API key | `anthropic/claude-haiku-5-5`, `openai/gpt-5-mini`, `gemini/gemini-2.5-flash`, `ollama/qwen3`, … (any LiteLLM string) | The provider's key (not needed for Ollama) |
| Demo | `demo` | Nothing; fake verdicts for trying the UI |

`texclaim config show` lists which agent CLIs are installed. Prefer `cli:claude` or `cli:pi`:
they run with all tools disabled. `cli:agy` cannot disable its tools and runs sandboxed in plan
mode. The prompts contain text from third-party papers, so tools are a prompt-injection risk.

## 3. Configure (CLI)

```bash
texclaim config set TEXCLAIM_MODEL=cli:claude            # default model for every project
texclaim config set ANTHROPIC_API_KEY                    # no value: prompts without echo (user types it)
texclaim config set OPENALEX_API_KEY ASTA_API_KEY        # optional source keys (prompted)
texclaim config set TEXCLAIM_CONTACT_EMAIL=user@uni.edu  # polite identification for OpenAlex/arXiv
texclaim config set TEXCLAIM_REPORT_LANGUAGE=es TEXCLAIM_CLAIM_SCOPE=auto TEXCLAIM_MAX_USD=5
texclaim config unset OPENAI_API_KEY
texclaim config test                                     # tiny request to the default model
texclaim config test --model cli:agy --openalex --asta
texclaim config path                                     # which .env file is used
```

Settable names: `TEXCLAIM_MODEL`, `TEXCLAIM_CONTACT_EMAIL`, `TEXCLAIM_REPORT_LANGUAGE`
(auto|en|es), `TEXCLAIM_CLAIM_SCOPE` (auto|sentence|two|paragraph), `TEXCLAIM_MAX_USD` (0-1000),
`AZURE_API_BASE`, `AZURE_API_VERSION`, `OLLAMA_API_BASE`, and the secrets `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `DEEPSEEK_API_KEY`, `GROQ_API_KEY`,
`OPENROUTER_API_KEY`, `AZURE_API_KEY`, `OPENALEX_API_KEY`, `ASTA_API_KEY`.

Precedence: command-line flag > environment variable > paper config (`<paper>/.texclaim/config.toml`)
> global config > default. Real environment variables beat the `.env` file.

## 4. Configure (HTTP API of the web app)

With `texclaim serve` running (default `http://127.0.0.1:8765`; the API docs are at `/api/docs`):

```bash
curl -s localhost:8765/api/config                                  # never contains secret values
curl -s -X PUT localhost:8765/api/config -H 'Content-Type: application/json' \
     -d '{"values": {"TEXCLAIM_MODEL": "cli:claude", "OPENAI_API_KEY": null}}'   # null removes
curl -s -X POST localhost:8765/api/config/test -H 'Content-Type: application/json' \
     -d '{"target": "model", "model": "cli:claude"}'                # or {"target": "openalex"|"asta"}
```

Per-project settings (`GET/PUT /api/projects/{id}/settings`) accept: `model`, `claim_scope`,
`report_language`, `internal_enabled`, `internal_sections`, `max_usd`, `offline`, `main`,
`evidence_strategy` (auto|full|passages), `full_text_max_tokens`, `passage_budget_tokens`,
`concurrency`, `source_order` (subset/order of local, cache, openalex_content, oa_locations,
arxiv, asta, abstract), `openalex_max_usd`, `arxiv_max_downloads`, `pdf_dirs`,
`extra_cite_commands`, `internal_max_claims`, `screening` (auto|llm|heuristic|none).
`null` means the default.

Other endpoints: `POST /api/projects` (multipart `files`, `name`), `POST /api/projects/local`
(`{"path": "/abs/folder"}`), `POST /api/projects/{id}/runs` (`{"force": false, "dry_run": false}`),
`GET /api/projects/{id}/events` (SSE progress), `GET /api/projects/{id}/report`,
`GET /api/projects/{id}/report.{md,json,html,docx}`, `GET /api/projects/{id}/graph`.

## 5. Run

```bash
texclaim check paper/ --dry-run            # plan and estimate, no model calls
texclaim check paper/                      # LaTeX, Markdown or Word; writes texclaim_report.{md,json}
texclaim check paper/ --model cli:claude --claim-scope two --internal-section Results
texclaim export paper/ --format docx       # or html
texclaim serve --open                      # web app
texclaim mcp paper/                        # knowledge graph over MCP (stdio) for agents
```

Exit codes: 0 no failing findings, 1 findings match `--fail-on`, 2 configuration error,
3 incomplete (provider errors, budget, interruption). Read `texclaim_report.json` for structured
results: `findings[]` (flagged), `units[]` (every check: `verdict`, `claim_text`, `quotes`,
`what_is_wrong`, `suggested_fix`, `claim_origin` cited|internal, `role` abstract|conclusion).

## 6. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `No model configured` | `texclaim config set TEXCLAIM_MODEL=...` |
| `cli:<agent>` "not installed" | install the CLI or choose another model |
| Agent CLI says not logged in / no credit | log in to that CLI (`claude`, `pi auth login`, `agy`) or switch model |
| Provider rejects the key | `texclaim config set <NAME>` again, then `texclaim config test` |
| Many works "Not found" | add `OPENALEX_API_KEY`, put PDFs at `papers/<bibkey>.pdf`, or upload them in Sources |
| Markdown/Word not read | install pandoc |
