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
