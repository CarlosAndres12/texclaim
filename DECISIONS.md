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
