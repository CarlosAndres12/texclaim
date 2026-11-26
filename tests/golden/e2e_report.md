# texclaim report

- texclaim <VERSION> · prompt 1.4 · model(s): fake/model · run <RUN> (completed)
- Run time: <TS> to <TS>
- Cost: LLM $0.0130 (13 calls) · OpenAlex $0.00
- Claims: 12 · checks: 17 · verified this run: 13 · reused: 4
- Sources: 3 full text · 1 abstract only · 4 none

## Findings

### F-042fd455 · Contradicted · sections/intro.tex:7

> Neural nets are used widely \cite{lecun1998}.

**What is wrong:** The source reports the opposite trend.

**What the source says:** Neural nets are rarely used.

**Evidence:** "Gradient-Based Learning Applied to Document Recognition Yann LeCun This study reports careful measurements of widgets un"  
lecun1998 · PDF page 1 · match 100 · [open](file://<PDF>#page=1)

**Suggested fix:** Neural nets are used rarely \cite{lecun1998}.

*Confidence: high · evidence: full text · model: fake/model*

## Uncheckable checks

### MISSING_BIB_ENTRY (1)
- `sections/intro.tex:4` `doe2024`: add an entry for `doe2024` to your .bib file

### NO_SOURCE (3)
- `sections/intro.tex:9` `footnoted2021`: add `papers/footnoted2021.pdf` (no open-access copy was found)
- `sections/sub/related.tex:4` `caption2022`: add `papers/caption2022.pdf` (no open-access copy was found)
- `sections/sub/related.tex:7` `he2016`: add `papers/he2016.pdf` (no open-access copy was found)

## Bibliography integrity

- **error** MISSING_BIB_ENTRY `sections/intro.tex:4` `doe2024` no .bib entry for `doe2024` (I-ed533262)
- **warning** DUPLICATE_BIB_KEY `references.bib` `smith2020` `smith2020` is defined in references.bib, more.bib; the first wins (I-b1cc32c9)
- **warning** UNKNOWN_CITE_MACRO `sections/sub/related.tex:11` \frobcite looks like a citation command (I-8fa59ea8)
- **warning** UNRESOLVED_INCLUDE `main.tex:14` \input{sections/missing} not found (I-e359b5f8)
- **info** PREPRINT_EVIDENCE `sections/intro.tex:2` `vaswani2017` evidence taken from a preprint version (I-6922c900)
- **info** UNKNOWN_CITE_MACRO `main.tex:3` \mycite wraps a citation command; registered as a citation macro (I-e352ce15)

## Sources

| key | OpenAlex | provider | version | status | file |
| --- | --- | --- | --- | --- | --- |
| caption2022 |  |  |  | not found |  |
| doe2024 |  |  |  | missing .bib entry |  |
| dosovitskiy2021 | W200 | abstract |  | abstract only | [open](https://doi.org/10.48550/arxiv.2010.11929) |
| footnoted2021 |  |  |  | not found |  |
| he2016 |  |  |  | not found |  |
| lecun1998 |  | your PDF |  | full text | [open](file://<PDF>) |
| smith2020 | W100 | open-access copy | published | full text | [open](file://<PDF>) |
| vaswani2017 |  | arXiv | preprint | full text | [open](file://<PDF>) |

## Suppressed findings

0 suppressed.
