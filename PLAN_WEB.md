# Plan v2: formats, claim scope, internal claims, web app

Builds on Phases 0-8 (see `PROGRESS.md`). Phases 9-17 are carried out autonomously, one commit per
phase gate (`make test lint` green). Decisions taken along the way go to `DECISIONS.md`.

## User answers (2026-11-26)

| Question | Answer |
| --- | --- |
| Web stack | FastAPI backend + React SPA (Vite, TypeScript) |
| LLM for tests | User adds keys to an empty `.env` file I generate; the fake verifier is used until keys exist |
| Claim length | "default is 2, 1 is available": default `auto` (the LLM decides the span), manual setting also available: `sentence` (1), `two` (2 sentences), `paragraph` |
| Internal claims | Whole document by default; option to select certain sections |

## Phase 9: keys file and input formats (Markdown, Word)

- `.env.example` (committed) and an empty `.env` (git-ignored) at the repo root with
  `TEXCLAIM_MODEL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENALEX_API_KEY`.
  The CLI and `texclaim serve` load `.env` from the cwd and the repo root without overriding real
  environment variables. Keys are never sent to the browser.
- New `texclaim/formats/`: `detect(folder)` picks LaTeX, Markdown or Word.
- Markdown and Word are converted with pandoc (`markdown`/`docx` reader to `latex --biblatex`)
  into a shadow LaTeX tree in `.texclaim/shadow/`, then go through the existing parser unchanged
  (sentences, captions, footnotes and tables all work).
  - Citations: pandoc `[@key]`/`@key` with a `.bib` (front-matter `bibliography:` or any `.bib`
    in the folder); Word Zotero/Mendeley/EndNote fields (pandoc reads them; references become CSL
    → converted to `.bib`); numeric `[1]`, `[2-4]` and a "References"/"Referencias" list in Word or
    Markdown → synthesised bib entries (title, year, authors, DOI parsed from each reference string).
  - Locations are mapped back to the original file (Markdown line, Word paragraph number) by
    matching the claim text; reports and the web UI show the original location.
- Tests: conversion of md/docx fixtures, citation forms, location mapping.

## Phase 10: claim length (`claim_scope`)

- Setting `claim_scope = auto | sentence | two | paragraph` (config, `--claim-scope`, web form).
  - `auto` (default): sentence plus surrounding context; the prompt asks the model to decide
    which span the citation covers and report it in `claim_scope`.
  - `sentence`: the citing sentence only, no context.
  - `two`: the citing sentence plus the preceding sentence of the same paragraph form the claim.
  - `paragraph`: the whole paragraph is the claim.
- The scope is part of the claim hash, so changing it re-verifies; prompt version bumped.

## Phase 11: internal claims and conclusions

- `internal_checks = true` by default; `internal_sections = []` (empty = whole document) or a list
  of section titles/patterns (web: checkbox list of the manuscript's sections).
- Uncited sentences are first screened in batches by the LLM for check-worthiness (factual,
  quantitative, comparative, "we show/demonstrate"); the fake verifier screens by heuristics.
- Each check-worthy sentence becomes a unit with bib key `@self`; the evidence is the manuscript
  itself (indexed by section with the existing chunker/FTS), excluding the claim's own paragraph.
  Verdicts: SUPPORTED / PARTIALLY_SUPPORTED / CONTRADICTED / NOT_FOUND (no support elsewhere in the
  document) with quotes verified in code as for citations.
- Abstract and Conclusion(s)/Conclusiones claims are labelled and get their own report section
  ("Conclusions consistency").

## Phase 12: source files

- API and CLI (`texclaim sources export`) to get each cited work's file: cached PDF (from local
  folder, OpenAlex, arXiv), else extracted text (`.txt`), else abstract; OA landing URL listed.
- Upload a missing PDF for a bib key (saved as `papers/<key>.pdf`, then re-resolved).
- Report downloads: Markdown, JSON, HTML and Word (`.docx` via pandoc).

## Phase 13: web backend (`texclaim serve`)

- FastAPI app in `texclaim/web/`, served by uvicorn, default `127.0.0.1:8765`.
- Projects: upload a `.zip`, single `.tex`/`.md`/`.docx` (+ `.bib`, PDFs), or open a local folder
  path; uploads stored under the user data dir.
- Endpoints: projects CRUD, settings, outline (sections), run check (background task; progress via
  Server-Sent Events; cancel), results, claim detail, sources, file download/upload, PDF streaming
  with range support, reports, health (model configured? which keys present, never values).
- API tests with the FastAPI test client and the fake verifier (`TEXCLAIM_MODEL=fake` enables a
  demo verifier that gives varied, deterministic verdicts).

## Phase 14: React frontend (`web/`)

- Vite + React + TypeScript + react-router + react-i18next (es/en, browser default, toggle,
  persisted), pdf.js viewer. Built into `src/texclaim/web/static/` (committed so a pipx install
  needs no Node).
- Pages: Home (projects, new project upload), Project settings (model, claim length, internal
  checks + section picker, language, budget), Run (live progress, cost, cancel), Results (summary
  cards, filterable findings table: verdict, kind, section, file), Claim detail (sentence, verdict,
  explanation, quotes, suggested fix, side-by-side embedded PDF opened at the quote page with the
  quote highlighted), Document view (manuscript text with claims highlighted by verdict),
  Sources (status, download PDF/text, upload missing PDF), Settings/Help.
- Accessible: labels, keyboard navigation, contrast; responsive.

## Phase 15: examples

- `examples/latex/`, `examples/markdown/` (Spanish), `examples/word/` (`.docx`, generated from a
  script with pandoc, numeric references), each a short paper citing real open-access arXiv works
  (Transformer, ResNet, BERT, Adam, Dropout) with a mix of correct, overstated, wrong-number and
  unsupported claims, uncited internal claims, and a conclusion that contradicts its own results.
- `examples/README.md` lists the expected findings. No third-party PDFs are committed; arXiv
  downloads happen at run time. Offline test copies use synthetic PDFs.

## Phase 16: Playwright testing loop

- Deterministic e2e suite (`tests/e2e/`, pytest-playwright, Chromium) against `texclaim serve`
  with the demo verifier: create project from each example, run, inspect results, open the PDF
  viewer, download files, switch language.
- Blind agent loop: a subagent that has not seen the code gets only the URL and a user persona
  with tasks (in Spanish and English), drives the app with Playwright scripts and screenshots,
  and reports bugs and confusing UI. I fix everything it finds and repeat until a full pass
  reports no bugs (cap 8 rounds; remaining issues are listed in `PROGRESS.md`).

## Phase 17: live pass and docs

- If `.env` has a model and key: run the three examples live, compare with the expected findings,
  tune prompts if needed, run the blind agent once on live results.
- README (web app, formats, new settings), `PROGRESS.md`, `DECISIONS.md`.
