# texclaim

Checks that each cited statement in a LaTeX, Markdown or Word manuscript is supported by the work
it cites, checks uncited statements, the abstract and the conclusions against the manuscript's own
results, and on later runs re-checks only what changed. Use it from the command line or from a web
app in English or Spanish.

```text
texclaim check path/to/paper        # command line
texclaim serve --open               # web app at http://127.0.0.1:8765
```

## Web app

`texclaim serve` starts a local web app (no login, bound to 127.0.0.1). Create a project by
uploading a folder, a `.zip` or single files (or by opening a local folder in place), pick the
model, claim length and which sections to check, then run. Results update live. Then you can:

- **Overview**: verdict breakdown for citations and for internal claims, source coverage, cost,
  and downloads (HTML, Word, Markdown, JSON reports; all source files as a `.zip`).
- **Findings**: filter by verdict, kind (citations, internal claims, abstract and conclusions) and
  text. Each finding shows the explanation and suggested fix, and the cited PDF opens next to it at
  the quoted page with the quote highlighted (keys: <kbd>j</kbd>/<kbd>k</kbd>).
- **Document**: the manuscript with each claim coloured by its verdict.
- **Sources**: each cited work's status. View or download its PDF (or the extracted text or
  abstract), and upload the PDF of a closed-access work.
- **Graph**: a knowledge graph of sections, claims, cited works and the entities they mention
  (methods, datasets, metrics, results), coloured by verdict, with search, layouts and PNG/JSON export.

The UI language follows the browser and can be switched (EN/ES); there are light and dark themes.

## Formats

| Format | Citations | Bibliography |
| --- | --- | --- |
| LaTeX | `\cite`, natbib, biblatex | `.bib` |
| Markdown | pandoc `[@key]`, `@key`; or `[1]`, `[2-4]`, `(He et al., 2016)` | YAML `bibliography:`, any `.bib`, or a final "References" list |
| Word (`.docx`) | Zotero/Mendeley/EndNote fields, typed `[@key]`, numeric or author-year | embedded citation data, a `.bib`, or the "References" list |

Markdown and Word need [pandoc](https://pandoc.org). Locations in reports are lines for Markdown
and paragraphs (`¶`) for Word. See `examples/` for one manuscript in each format.

## Claim length and internal checks

`claim_scope` sets how much text each citation is checked against: `auto` (default; the model
decides from the sentence and its neighbours), `sentence`, `two` (the citing sentence and the one
before it) or `paragraph`.

Internal checks are on by default. Uncited statements are screened for check-worthiness, and the
abstract and conclusions are always checked. Each is then compared with the rest of the manuscript.
A statement backed only by its own restatement in the abstract or conclusions counts as unsupported.
Limit the checks to some sections with `internal.sections` (or the section picker in the web app).

```bash
texclaim check paper --claim-scope two --internal-section Results --internal-section conclusion
texclaim check paper --no-internal
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

Copy `.env.example` to `.env` (git-ignored) and fill it in, or export the variables:

```bash
export TEXCLAIM_MODEL="<provider>/<model>"      # or "demo" for fake verdicts without a key
export OPENAI_API_KEY=...        # or ANTHROPIC_API_KEY, GEMINI_API_KEY, ... (LiteLLM reads these)
export OPENALEX_API_KEY=...      # optional: free key, higher limits, full-text downloads
export ASTA_API_KEY=...          # optional: Asta / Semantic Scholar, a further source of PDFs and abstracts
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
| `texclaim serve` | The web app (`--host`, `--port`, `--open`) |
| `texclaim export --format html\|docx` | Convert the Markdown report |
| `texclaim sources export` | Copy each cited work's PDF (or text) into `sources_export/` |
| `texclaim graph [--llm]` | Build the knowledge graph (`.texclaim/graph.json`) |
| `texclaim mcp [FOLDER]` | Serve the knowledge graph to agents over MCP (stdio) |

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

## Knowledge graph and agents

Every check also builds a knowledge graph. Nodes are sections, claims, cited works and entities;
edges are citations (with their verdicts), evidence links between internal claims and the sections
that back them, and mentions. It is stored in `.texclaim/graph.json`. Entities are extracted by the
model when one is configured, otherwise by heuristics, and are cached per claim. As CodeGraph does
for code, `texclaim mcp` exposes the graph to agents with the tools `graph_search`,
`graph_neighbors`, `claim_detail` and `findings`:

```bash
claude mcp add texclaim -- texclaim mcp /path/to/paper
```

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
make web                                # rebuild the React UI into src/texclaim/web/static
make e2e                                # browser tests (Playwright, Chromium)
TEXCLAIM_LIVE_TESTS=1 pytest -m live    # real network and LLM calls, opt-in
```

The web UI lives in `web/` (Vite, React, TypeScript, Tailwind, Radix). `npm run dev` there proxies
`/api` to a running `texclaim serve`.

See `PROGRESS.md` for build status and `DECISIONS.md` for design choices made along the way.
