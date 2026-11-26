# texclaim user guide

texclaim checks whether the works you cite support what your manuscript says. It also checks your
own uncited statements, abstract and conclusions against your results. It reads LaTeX, Markdown
and Word, and has a web app in English and Spanish. *Versión en español: [GUIA.md](GUIA.md).*
For AI agents: [../AGENTS.md](../AGENTS.md).

## 1. Start the web app

```bash
texclaim serve --open          # http://127.0.0.1:8765
```

Everything in this guide can be done from the web app. Nothing requires editing files.

## 2. Connect a model (Settings page)

Open **Settings** in the top bar. You have three options:

1. **An agent CLI you are logged in to: no API key.** If Claude Code, pi or Antigravity is
   installed on this computer, it appears under *Agent CLIs* with a **Test** button. Click
   **Use as default**. Model strings: `cli:claude`, `cli:pi`, `cli:agy`; add `/model` to pick one,
   for example `cli:claude/haiku`. These bill your subscription, so costs show as $0. Claude Code
   and pi run with all tools disabled, which makes them the safest choice.
2. **An API key.** Paste the key under *Model provider API keys* (Anthropic, OpenAI, Gemini,
   Mistral, DeepSeek, Groq, OpenRouter, Azure) and press **Save**, then **Test**. Choose a model
   such as `anthropic/claude-haiku-5-5` under *Default model*. Any
   [LiteLLM](https://docs.litellm.ai/docs/providers) model string works; local Ollama models
   (`ollama/qwen3`) need no key.
3. **Demo.** `demo` gives fake verdicts so you can explore the interface for free.

Keys are stored on this computer in a `.env` file that only you can read. The browser never
receives them; the page only shows *Set* or *Not set*.

**Sources (optional).** An OpenAlex key and an Asta (Semantic Scholar) key let texclaim find more
full texts with higher limits. A contact email identifies you politely to OpenAlex and arXiv.

**Defaults.** Explanation language, claim length and the cost limit per run. Each project can
override them.

## 3. Create a project

**New project** → drag a folder, a `.zip` or files (`.tex` + `.bib`, `.md`, `.docx`, and PDFs of
cited works if you have them). Or open a local folder in place; reports are then written next to
your manuscript.

## 4. Project settings

| Setting | Meaning |
| --- | --- |
| Model | Overrides the default model for this project |
| Claim length | `auto` (the model decides what each citation covers), 1 sentence, 2 sentences, or the whole paragraph |
| Check uncited claims and conclusions | Uncited statements, the abstract and the conclusions are compared with your own results; pick sections or leave all unticked for the whole document |
| Explanation language | Language of explanations and reports (auto follows the manuscript) |
| Maximum cost | The run stops before exceeding it |
| Offline | Use only PDFs you provided and the cache |
| **Advanced** | Evidence (full text or passages), token limits, parallel checks, which sources to try and in what order, OpenAlex/arXiv limits, PDF folders, extra citation macros, how uncited statements are screened |

Changes save automatically.

## 5. Run and review

Press **Check now**. The *Run* tab shows each step and each verdict as it arrives. Then:

- **Overview**: verdicts for citations and internal claims, source coverage, cost, downloads
  (HTML, Word, Markdown, JSON reports; all source files as `.zip`).
- **Findings**: filter and search. Each finding shows what is wrong, what the source says, a
  suggested fix, and the cited PDF opened at the quoted page with the quote highlighted.
- **Document**: your manuscript coloured by verdict.
- **Sources**: each cited work's status. View or download its PDF, or upload one that is missing.
- **Graph**: a knowledge graph of sections, claims, cited works and the entities they mention.

Later runs check only what changed. **Re-check everything** asks before replacing results.

## 6. Verdicts

| Verdict | Meaning |
| --- | --- |
| Supported | The source states or directly implies the claim |
| Partially supported | The core holds, but the claim overstates, rounds or widens it |
| Contradicted | The source (or your own results) say something different |
| Not found | The whole source was read and does not address the claim |
| Uncheckable | The available text cannot settle it (no PDF, abstract only, a primary measurement) |

## 7. Command line equivalents

```bash
texclaim config show | set NAME=VALUE | set SECRET_NAME | unset NAME | test [--model M] [--openalex] [--asta]
texclaim check PAPER [--model M] [--claim-scope auto|sentence|two|paragraph] [--internal-section S] [--dry-run]
texclaim export PAPER --format html|docx
texclaim sources export PAPER
texclaim doctor
```

## 8. Privacy

Manuscript sentences and source passages are sent to the model you choose: an agent CLI, a
provider API, or a local Ollama model. For confidential work, use a local model.
