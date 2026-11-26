# Progress

- [x] Phase 0: Scaffold and global install
- [x] Phase 1: Config, paths and database
- [x] Phase 2: LaTeX parsing
- [x] Phase 3: Bibliography, sources and global cache
- [x] Phase 4: Extraction and index
- [x] Phase 5: Verification engine
- [x] Phase 6: Incremental planning and resume
- [x] Phase 7: Reports, CLI polish, end-to-end
- [ ] Phase 8: Evaluation harness (needs the author)
  - [x] `evals/` runner, perturbation generator, metrics with Wilson intervals, `make eval` (built and tested offline)
  - [ ] The author labels at least 50 units from their own papers into `evals/gold/*.jsonl` (see `evals/gold/README.md`)
  - [ ] Gate: `make eval MODEL=<model>` writes a results file; record the numbers below and compare with the release bar
  - Results: _not run yet_

## Plan v2 (PLAN_WEB.md)

- [x] Phase 9: `.env` keys file; Markdown and Word manuscripts (pandoc shadow LaTeX, numeric and author-year reference lists)
- [x] Phase 10: claim length (`claim_scope` auto / sentence / two / paragraph)
- [x] Phase 11: internal claims and conclusions consistency (`@self` source, screening, self-quote rejection)
- [x] Phase 12: source downloads (`texclaim sources export`), report formats (HTML, Word)
- [x] Phase 12b: Asta / Semantic Scholar provider (MCP endpoint, batched, cached)
- [x] Phase 13: web backend (`texclaim serve`), demo verifier
- [x] Phase 14: React web app (EN/ES, light/dark), embedded PDF viewer with quote highlighting
- [x] Phase 14b: knowledge graph (entities, networkx, Sigma.js view, MCP server `texclaim mcp`)
- [x] Phase 15: examples (LaTeX, Spanish Markdown, Word) with expected findings
- [ ] Phase 16: Playwright suite (`make e2e`, done) and blind-agent test loop (in progress)
- [ ] Phase 17: live pass on all examples, docs
