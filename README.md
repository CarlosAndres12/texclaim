# texclaim

Checks that each cited statement in a LaTeX manuscript is supported by the work it cites, and on
later runs re-checks only what changed.

```text
texclaim check path/to/paper
```

texclaim finds the root `.tex` file, walks its includes, extracts every sentence, caption,
footnote and table row that cites something, obtains the cited works' text (your local PDFs, a
global cache, OpenAlex, arXiv), asks an LLM through [LiteLLM](https://docs.litellm.ai) whether each
source supports its statement, verifies the model's quotes against the source text in code, and
writes `texclaim_report.md` and `texclaim_report.json` next to your manuscript. It never modifies
your `.tex` or `.bib` files.

## Install

Needs Python 3.11+ and [pipx](https://pipx.pypa.io).

```bash
make install-global        # pipx install --editable, once, for the whole machine
texclaim --version         # open a new shell first if the command is not found
```

Code edits under `src/texclaim/` take effect immediately. A new dependency, a changed entry point
or a version bump needs `texclaim self-install` (or `make install-global`) again.
On Windows run `pipx install --editable . --force` directly.

## Configure

A model is required; there is no default. Any LiteLLM model string works:

```bash
export TEXCLAIM_MODEL="<provider>/<model>"
export OPENAI_API_KEY=...        # or ANTHROPIC_API_KEY, GEMINI_API_KEY, ... (LiteLLM reads these)
export OPENALEX_API_KEY=...      # optional: free key, higher limits, full-text downloads
```

`texclaim init <paper>` creates `<paper>/.texclaim/config.toml` and offers to request a free
OpenAlex key. Settings resolve as CLI flag, environment, paper config, global config, default.
**Secrets are never read from the paper config**; texclaim refuses a key-like field there. Keys
belong in the environment, the OS keyring (`pip install texclaim[keyring]`) or the global config
(`~/.config/texclaim/config.toml`, mode 0600).

```toml
# <paper>/.texclaim/config.toml  (safe to commit)
model = "<provider>/<model>"
report_language = "auto"          # auto (follows the manuscript) | en | es
fail_on = ["contradicted", "missing_bib_entry"]
pdf_dirs = ["papers"]

[budget]
max_llm_usd_per_run = 5.00
```

## Daily use

| Command | What it does |
| --- | --- |
| `texclaim check [FOLDER]` | Full pipeline; writes the reports. `--dry-run` plans and estimates cost |
| `texclaim fetch [FOLDER]` | Resolve and download sources, no LLM; prints which PDFs you must add |
| `texclaim status` / `show --at FILE:LINE` | Counts, or one unit in full with quotes and page links |
| `texclaim ignore F-xxxxxxxx --reason "..."` | Suppress a finding (`unignore` reverses it) |
| `texclaim clean` | Delete the paper's state; config and suppressions stay |
| `texclaim cache info\|prune\|path` | Inspect or shrink the global cache |
| `texclaim doctor` | Check the install, FTS5, keys (never printed), OpenAlex, model support |

Closed-access papers: put the PDF at `papers/<bibkey>.pdf` (a Zotero storage folder listed in
`pdf_dirs` also works). `texclaim fetch` prints the exact paths still missing.

Only new or changed claims and sources are re-verified; an interrupted run resumes by itself
(`--resume` continues an interrupted `--force`/`--recheck`). Changing the model re-verifies
nothing unless you pass `--recheck stale-model`.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Completed, no finding matches `--fail-on` |
| 1 | Completed, at least one finding matches `--fail-on` |
| 2 | Usage or configuration error (no model, a secret in the paper config, a concurrent run) |
| 3 | Incomplete: provider errors, exhausted budget or interruption (takes precedence over 1) |

Suppress inline with `% texclaim: ignore[bibkey] reason` on the claim's line or the line above.

## Confidentiality

texclaim sends manuscript sentences and source passages to the model provider you configure. For
unpublished or confidential work, point `model` at a local backend such as Ollama.

`<paper>/.texclaim/` holds copyrighted source text in `state.db`. It git-ignores itself, but check
before zipping the folder for arXiv or a journal, or syncing it to Overleaf; run `texclaim clean`
if in doubt. Do not keep `.texclaim/state.db` on network drives or synced folders: SQLite WAL
mode is unreliable there (state can always be rebuilt).

OpenAlex and arXiv are queried only for works your manuscript cites, within their rate limits;
texclaim never bypasses access controls.

## Development

```bash
uv venv && uv pip install -e '.[dev]'
make test lint
TEXCLAIM_LIVE_TESTS=1 pytest -m live    # real network and LLM calls, opt-in
```

See `PROGRESS.md` for build status and `DECISIONS.md` for design choices made along the way.
