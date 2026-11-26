# Example manuscripts

Three short papers to try texclaim and to test it. Each cites real open-access arXiv papers
(Transformer, ResNet, BERT, Adam, Batch Normalization), which texclaim downloads at run time; no
third-party PDFs are stored here. Each contains correct claims, deliberate citation errors, and an
abstract or conclusion that its own results do not back.

```bash
texclaim check examples/latex          # or examples/markdown, examples/word
texclaim serve                         # then "New project" → upload one of these folders
```

Rebuild the Word file after editing `src/word_source.md` with `make examples` (needs pandoc).

## `latex/` (English, `\cite` + BibTeX)

| Where | Statement | Expected |
| --- | --- | --- |
| Intro | Transformer 28.4 BLEU on WMT 2014 En-De | Supported |
| Intro | Trained 3.5 days on eight P100 GPUs | Supported |
| Intro | 152-layer ResNets won ILSVRC 2015 classification | Supported |
| Intro | BERT outperforms human annotators on every GLUE task | Contradicted / not found (overstated) |
| Background | Adam requires a large amount of memory | Contradicted (the paper says little memory) |
| Background | Batch norm: same accuracy with 14 times fewer steps | Supported |
| Background | ResNet 3.57% top-5 test error; Transformer 41.8 BLEU En-Fr | Supported |
| Background | BERT-large has 340M parameters | Supported |
| Abstract | Improves accuracy by 3.2 points; trains twice as fast | Supported by Results (91.2 vs 88.0; 2.1 h vs 4.0 h) |
| Conclusions | Improves accuracy by more than 5 points | Contradicted by Results (3.2) |
| Conclusions | Gains hold equally out of domain and in every language | Contradicted / not found (79.5 vs 78.9; one language) |

## `markdown/` (Spanish, pandoc `[@key]` citations + YAML `bibliography`)

| Where | Statement | Expected |
| --- | --- | --- |
| Introducción | Transformer 30,1 BLEU En-De | Contradicted (28.4) |
| Introducción | ResNet 152 capas ganó ILSVRC 2015 | Supported |
| Introducción | BERT GLUE 80,5, mejora absoluta de 7,7 | Supported |
| Antecedentes | Adam eficiente y con poca memoria | Supported |
| Antecedentes | Batch norm elimina por completo la necesidad de regularización | Partially supported (the paper says it reduces the need for Dropout "in some cases") |
| Resumen / Conclusiones | Mejora de 2,5 puntos | Supported (87,5 vs 85,0) |
| Conclusiones | Reduce el tiempo de entrenamiento a la mitad | Contradicted (1,5 h vs 1,6 h) |

## `word/` (English `.docx`, numbered reference list, no `.bib`)

| Where | Statement | Expected |
| --- | --- | --- |
| Introduction | Residual learning made 100+ layer networks trainable [1] | Supported |
| Introduction | ResNet ensemble 3.57% top-5 test error [1] | Supported |
| Introduction | Batch norm 14 times fewer steps [2] | Supported |
| Introduction | Adam combines AdaGrad and RMSProp advantages [3] | Supported |
| Introduction | Adam always converges faster than every optimizer on all problems [3] | Contradicted / not found (overstated) |
| Introduction | Transformers are trained with Adam (Vaswani et al., 2017) | Supported (author-year matched to reference 4) |
| Abstract | 94.1%, 1.3 points above the baseline | Supported (94.1 vs 92.8) |
| Conclusions | Batch norm adds 1.1 points | Supported (94.1 vs 93.0) |
| Conclusions | Best known result on CIFAR-10 | Not found (nothing in the paper backs it) |
