# Gold set

Put your labeled units in `evals/gold/*.jsonl` (one JSON object per line; lines starting with `#`
and files named `example*` are skipped). You need at least 50 units from your own papers to meet
the v1 gate. Do not commit copyrighted PDFs: reference them by path and keep them outside git
(add them to `.gitignore`), or paste the relevant source text into `source_text`.

```json
{"id": "p1-017", "claim": "Chen et al. [@chen2023] reach 94.2% top-1 accuracy without pretraining.",
 "key": "chen2023", "source_pdf": "pdfs/chen2023.pdf", "label": "CONTRADICTED",
 "postnote": "Table 3", "notes": "94.2% needs JFT-300M"}
```

Fields: `id`, `claim` (sentence text, citations as `[@key]`), `key`, `label` (`SUPPORTED`,
`PARTIALLY_SUPPORTED`, `CONTRADICTED`, `NOT_FOUND`, `UNCHECKABLE`), and one of `source_pdf`
(relative to this folder) or `source_text`. Optional: `source_id` (shared by units citing the same
source), `prenote`, `postnote`, `cite_command`, `attributed_span`, `section`, `context`,
`scope: "abstract"` (to evaluate at abstract scope), `source_language`.

Labeling rules: label what the *source* says about the *attributed* claim. Use `NOT_FOUND` only
when the whole paper does not address the claim. Mix verdicts: aim for at least 10 units each of
`SUPPORTED` and `CONTRADICTED`/`PARTIALLY_SUPPORTED`, because precision on a verdict needs both.

Then run `make eval MODEL=<model>` (add `ARGS="--perturb"` for synthetic perturbations of your
`SUPPORTED` units: changed numbers, flipped comparatives, dropped qualifiers, widened scope, swapped
keys). Results land in `evals/results/<date>-<model>.json`; copy the headline numbers into
`PROGRESS.md`. The v1 release bar is `CONTRADICTED` precision >= 0.8 and a false-alarm rate on
supported units <= 10%; the numbers are recorded either way.
