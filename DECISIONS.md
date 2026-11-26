# Decisions

| Date | Question | Choice | Reason |
| --- | --- | --- | --- |
| 2026-10-28 | Lint rule set | ruff E,F,I,UP,B, line length 100 | Simplest useful default; plan only requires check + format |
| 2026-10-28 | constraints.txt source | Frozen from dev venv (includes dev deps) | pipx runpip not available before first install; harmless extra pins |
| 2026-10-28 | Download defaults | OpenAlex content on with key (cap $0.50/run); arXiv on (3s, 30/run) | User answer |
| 2026-10-28 | Report location/language | Paper root; report_language = "auto" (es if manuscript detected Spanish, else en) | User answer |
| 2026-10-28 | Neighbour edits / release bar | No re-verify; precision>=0.8, false alarms<=10% | User answer (plan defaults) |
| 2026-10-28 | Default model / LLM cap | No default model; max_llm_usd_per_run = 5.00 | Plan §5 |
| 2026-10-28 | Workflow | Phases 1-7 autonomous, git commit per phase gate | User answer |
| 2026-10-28 | Extra parser helper modules | Added parser/tex.py (brace matching, line index) and parser/text.py (pylatexenc wrapper) | Shared by several parser modules; not in §3 layout |
| 2026-10-28 | Sentence start vs masked span | A citation command may start a sentence (e.g. `\citet{x} showed`); other masked spans (math, refs) never do | §6.5 says masked spans never start a sentence but also lists backslash as a starter; textual citations need it |
| 2026-10-28 | Paragraph breaks | Cut paragraphs at \begin/\end (non-math), sectioning, \input-family, \title etc., and \item | Without it, headings and floats merge into the neighbouring sentence |
| 2026-10-28 | Empty attributed span | Falls back to the whole sentence when a citation opens the sentence | A hint of '' is useless to the verifier |
| 2026-10-28 | citations.unit_key at parse time | Left '' by the parser; Phase 6 fills it once sources are resolved | Key depends on source hash |
| 2026-10-28 | Include de-duplication | A file included twice is parsed once (first inclusion) | Avoids duplicate claims |
| 2026-10-28 | GROBID TEI download | Not fetched in v1 (`has_grobid` is recorded only) | TEI is used only for section headings (Phase 9); each file costs $0.01 |
| 2026-10-28 | Local PDF size rule | The 10 KB minimum applies to downloads only; local PDFs need just the `%PDF-` header | User-supplied files are trusted more; also small test PDFs |
| 2026-10-28 | Snapshot writer | `snapshot.write_snapshot` replaces source_files, claims, citations and references_catalog in one transaction; citations.unit_key stays '' until Phase 6 | §9 |
| 2026-10-28 | Inactive OpenAlex key | On `403 key_not_activated` the client retries once without the key and continues keyless | §5 |
| 2026-10-28 | Validator hook | `Locator` takes a `SourceValidator`; Phase 4 adds scanned-PDF detection to it so the cascade falls through | §11.1 says a scanned PDF falls through to the abstract |
| 2026-10-28 | Reference-list detection | Last "References"-type heading after 30% of the text, ending at the next "Appendix" heading; a chunk is bibliography when half of it lies in that region and it has >=3 years and a venue token | Keeps appendices after the references (§8) |
| 2026-10-28 | Heading isolation | Headings are put on their own paragraph during normalisation so they survive line-joining | Needed for section hints and the reference heading |
| 2026-10-28 | Global text cache payload | Pages and meta only; chunks are recomputed (deterministic) when copied into a paper DB | Smaller cache, chunk ids stay stable |
| 2026-10-28 | Scanned detection | Average <200 characters per page; the validator makes the cascade fall through to the next provider | §8, §11.1 |
| 2026-10-28 | Block ids | Page blocks `P<n>`, chunk blocks `<sha12>:<ordinal>`, abstract `ABSTRACT`; the quote's block_id is matched leniently and falls back to a search in all blocks | Models copy ids imperfectly; position comes from the match, not the id |
| 2026-10-28 | Token estimate | chars/4 for the strategy decision and passage budget; litellm.token_counter only for --dry-run | Strategy must not depend on the model (D6); cheap and deterministic |
| 2026-10-28 | Retry policy | At most one retry per unit, covering unparsable JSON, unverifiable quotes and missing explanations; feedback names the problem | §11.5 |
| 2026-10-28 | Cross-language terms cache | Stored in the global cache.db (`query_terms`), an internal table | §11.2 says cache by (claim_hash, language); the paper DB schema is a public contract |
| 2026-10-28 | Cost budget | reserve/settle around each call using the running average cost; the first call uses `verifier.estimate_cost` if present | Stops scheduling without needing price tables |
| 2026-10-28 | Phase 2 gate command | `check --dry-run` now also resolves sources (needed for token estimates), so the Phase 2 CLI test passes `--offline`; it still lists every claim | Dry-run per §11.6 needs sources; the listing behaviour is unchanged |
| 2026-10-28 | Run status on provider errors | Run ends `completed`; errors go to run_errors and the CLI exits 3 | §10.4: errors are never cached and retried on the next plain run; only interrupted/budget_exhausted runs are resumable |
| 2026-10-28 | Selector storage | `--force`/`--recheck` selector is kept inside runs.settings_json under "selector" | No schema change; `--resume` reads it back |
| 2026-10-28 | Deterministic results | Written once per unit key, never re-queued by --force | They cost nothing and change only when the source status changes (new key) |
| 2026-10-28 | Report data model | One dict (json_report.build_report) rendered to both Markdown and JSON; unit keys are read back from citations.unit_key, not recomputed | Single source of truth; avoids key drift if settings differ |
| 2026-10-28 | Integrity persistence | Computed at the end of `check` (needs the OpenAlex work objects) and stored in integrity_issues; `show`/`status` read the DB | Author surnames and retraction flags are not in references_catalog |
| 2026-10-28 | Extra integrity codes | Added MALFORMED_BIB_ENTRY, MISSING_BIB_FILE and EMPTY_CITE_KEY alongside the §13.1 list | They already exist as statuses/diagnostics; hiding them would be worse |
| 2026-10-28 | fail_on vocabulary | Lower-case verdicts (contradicted, partially_supported, not_found, uncheckable), needs_review, claim flags (no_support, padding) and integrity codes | §12 only names two examples |
| 2026-10-28 | Report language | `report_language=auto` resolves once per run from the claims' stopword ratio and is used for model explanations; it is not part of unit keys | User chose auto-match; changing language alone should not re-verify |
| 2026-10-28 | Finding ids | `F-` + unit_key[:8] for units; `C-<claim_pk>` for claim flags (not stable across edits, not suppressible); `I-` + hash for integrity issues | §13 only fixes the unit form |
| 2026-10-28 | Golden files | tests/golden/e2e_report.{md,json}; regenerate with UPDATE_GOLDEN=1 after reviewing the diff | §14 |
| 2026-11-26 | Markdown/Word support | pandoc converts to a shadow LaTeX tree in `.texclaim/shadow/`; the LaTeX parser is reused unchanged; claims are mapped back to the original by normalised text search (Markdown line, Word paragraph) | Maximum reuse of the tested extractor (captions, footnotes, tables) |
| 2026-11-26 | Plain reference lists | A last "References/Referencias/Bibliografía" heading with numbered or bulleted items becomes `references-list.bib`; `[1]`, `[2-4]`, `(He et al., 2016)` and `Vaswani et al. (2017)` are rewritten to `[@refN]` only when every number/name matches an entry | Word manuscripts rarely have a .bib |
| 2026-11-26 | Keys file | `.env` in cwd and repo root, loaded by the CLI callback; never overrides real env; tests set TEXCLAIM_NO_DOTENV unless live | User asked for an empty file to fill in |
