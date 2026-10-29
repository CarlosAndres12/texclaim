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
