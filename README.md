# PaperPilot

[![PyPI](https://img.shields.io/pypi/v/paperpilot?color=2563eb&label=PyPI)](https://pypi.org/project/paperpilot/)
[![Python](https://img.shields.io/pypi/pyversions/paperpilot?color=0f766e&label=Python)](https://pypi.org/project/paperpilot/)
[![License](https://img.shields.io/github/license/CHB-learner/PaperPilot?color=f59e0b)](LICENSE)
[![Release](https://img.shields.io/github/v/release/CHB-learner/PaperPilot?color=7c3aed&label=Release)](https://github.com/CHB-learner/PaperPilot/releases)
[![CLI](https://img.shields.io/badge/CLI-PaperPilot-334155)](https://github.com/CHB-learner/PaperPilot)
[![Reports](https://img.shields.io/badge/Reports-ZH%2FEN%20MD%20HTML%20PDF-ef4444)](https://pypi.org/project/paperpilot/)
[![Workflow](https://img.shields.io/badge/Workflow-evidence--grounded-0891b2)](https://github.com/CHB-learner/PaperPilot)

[English](README.md) | [中文](README.zh-CN.md) | [Website](https://chb-learner.github.io/PaperPilot/)

<p align="center">
  <img src="docs/assets/paperpilot-hero.svg" alt="PaperPilot - AI literature review agent" width="100%">
</p>

PaperPilot is a **CLI research agent for AI-related literature review**.  
It turns one user request into a traceable, evidence-based research workflow and generates bilingual reports (`zh/en`) in Markdown, HTML, and PDF.

## ✨ What PaperPilot does

PaperPilot is not a chatbot. It is an **interactive scientific workflow**:

- Parse natural-language research requests
- Build an explicit search protocol with inclusion/exclusion rules
- Query multi-source literature APIs
- Normalize, deduplicate, and screen papers
- Verify URLs/PDF/code availability
- Synthesize evidence and generate review reports
- Output structured artifacts for reproducibility

Each run creates a dedicated folder under `runs/` with full state, logs, and intermediate files.

## 🚀 Highlights

### Core experience
- Natural-language intake with LLM-assisted interpretation
- Interactive shell with:
  - `/model` to manage LLM profiles
  - `/sources` to inspect search source/API status
  - `/doctor` for quick self-checks
- Multi-source retrieval with source registry and diagnostics
- Resume/inspect modes for reproducible research sessions

### Retrieval and screening
- Protocol-aware search using plan + diversified keywords
- Canonicalized `Paper` schema and robust deduplication
- Core/adjacent/excluded paper classification
- PDF + code-link verification (no paywall bypass)
- Optional full-text extraction from downloadable PDFs

### Reporting
- Canonical bilingual report model
- Consistent `[1][2][3]` citation mapping
- Method taxonomy and evidence matrix
- Markdown + HTML + PDF outputs with aligned content

### Quality controls
- Quality gates and reflection workflow
- Evidence ledger linking claims to corpus evidence
- Review checks for citation compliance and source reliability
- Event stream logs for auditability

## 🗂 Source stack

Default free sources:

- arXiv
- Semantic Scholar
- OpenAlex
- Crossref
- OpenReview
- PubMed / NCBI E-utilities
- Europe PMC
- bioRxiv / medRxiv
- DBLP
- ACL Anthology
- Papers.cool

Optional API-key sources:

- DeepXiv / Agentic Data
- CORE
- Lens.org Scholarly API
- IEEE Xplore
- Springer Nature
- Elsevier / Scopus
- Dimensions

## 🛠 Installation

```bash
python -m pip install paperpilot -i https://pypi.org/simple
```

Local development:

```bash
git clone https://github.com/CHB-learner/PaperPilot.git
cd PaperPilot
python -m pip install -e .
```

## ⚙️ LLM + Source Configuration

PaperPilot requires OpenAI-compatible LLM settings for query understanding, planning, synthesis, and report generation.

On first run, it creates an editable configuration template at:

```text
~/.paperpilot/config.json
```

Minimal default template:

```json
{
  "active": "default",
  "profiles": {
    "default": {
      "api_key": "",
      "base_url": "",
      "model": "gpt-5.2"
    }
  },
  "sources": {
    "core": {"enabled": null, "api_key": "", "base_url": ""},
    "lens": {"enabled": null, "api_key": "", "base_url": ""},
    "ieee": {"enabled": null, "api_key": "", "base_url": ""},
    "springer": {"enabled": null, "api_key": "", "base_url": ""},
    "elsevier": {"enabled": null, "api_key": "", "base_url": ""},
    "dimensions": {"enabled": null, "api_key": "", "base_url": ""},
    "deepxiv": {"enabled": null, "api_key": "", "base_url": ""}
  }
}
```

Notes:

- Leave optional source API keys empty if unavailable.
- `enabled: null` means auto-enable once a valid key is provided.
- `~/.paperpilot/config.json` is not committed; edit it directly or use CLI commands.

### CLI config commands

```bash
PaperPilot config set --base-url https://api.deepseek.com --model deepseek-chat
PaperPilot config import ./api.json
PaperPilot config list
PaperPilot config use deepseek
PaperPilot config show
PaperPilot --doctor
```

```bash
PaperPilot sources list
PaperPilot sources config core
PaperPilot sources config deepxiv
PaperPilot sources enable core
PaperPilot sources test core
```

Inside interactive mode, use `/sources` and `/doctor`.

## 🔑 API source keys references

| Source | Access page |
|---|---|
| CORE | https://core.ac.uk/services/api |
| Lens.org | https://docs.api.lens.org/ |
| IEEE Xplore | https://developer.ieee.org/getting_started |
| Springer Nature | https://dev.springernature.com/ |
| Elsevier / Scopus | https://dev.elsevier.com/ |
| Dimensions | https://docs.dimensions.ai/dsl/api.html |
| DeepXiv / Agentic Data | https://data.rag.ac.cn/api/docs |
| Papers.cool | https://papers.cool |

## 🧪 Quick Start

Interactive usage:

```bash
PaperPilot
```

Command mode example:

```bash
PaperPilot "RNA inverse folding sequence design" \
  --auto-confirm \
  --max-papers 50 \
  --since-year 2021 \
  --github-filter required \
  --sources auto \
  --mode apa \
  --quality balanced
```

Import local corpus and skip download:

```bash
PaperPilot "RNA inverse folding sequence design" \
  --auto-confirm \
  --user-corpus ./papers \
  --user-corpus references.bib \
  --no-download
```

Inspect/resume workflow:

```bash
PaperPilot inspect runs/<task-id>
PaperPilot resume runs/<task-id>
```

## 🧭 Workflow

PaperPilot follows this state-machine pipeline:

```text
Intake -> Protocol -> Search -> Corpus -> Screening -> Verification -> Synthesis -> Review -> Report
```

```mermaid
flowchart LR
  U[User request] --> C[Run context]
  C --> QA[Query understanding]
  QA --> PL[Planning + Protocol]
  PL --> ST[Source Registry search]
  ST --> NB[Corpus normalization]
  NB --> SC[Core/adjacent screening]
  SC --> VF[Verification + PDF + code checks]
  VF --> SY[Literature matrix]
  SY --> QG[Quality gate + reflection]
  QG --> EL[Evidence ledger]
  EL --> RP[Report render (ZH/EN)]
```

## 📁 Run artifacts

`runs/<task-id>/` will contain:

- `task.json` / `state.json` / `events.jsonl` / `manifest.json`
- `query_understanding.md` / `plan.json` / `protocol.json`
- `metadata.json` / `corpus.json` / `core_papers.json`
- `adjacent_papers.json` / `excluded_papers.json` / `ranked_papers.json`
- `verification.json` / `download_log.json` / `fulltext/` / `paper_notes.json`
- `literature_matrix.json` / `synthesis.json` / `quality_gate.json`
- `evidence_ledger.json` / `review_agent_findings.json`
- `report.canonical.json` / `report.zh.md` / `report.en.md`
- `report.zh.html` / `report.en.html` / `report.zh.pdf` / `report.en.pdf`
- `pdfs/` / `source_diagnostics.json` / `registries.json` / `prompt_manifest.json`

## 🧩 Code filter modes

- `any`: keep all papers and annotate code availability
- `required`: keep only papers with detected code repositories in final view
- `none`: keep only papers without detected public code links

## 🧪 CLI options (important ones)

```text
--max-papers INT                 maximum papers in final report view
--since-year INT                 preferred lower year bound
--github-filter any|required|none
--github-search-limit INT
--no-download                    skip PDF downloads
--pdf-limit INT                  maximum PDFs to download
--user-corpus PATH               repeatable local corpus path
--mode quick|apa|systematic
--interaction auto|gated
--quality fast|balanced|strict
--include-adjacent               include adjacent papers in appendices
--sources auto|all|core|biomed|cs|configured
--enable-source SOURCE           enable one source (repeatable)
--disable-source SOURCE          disable one source (repeatable)
```

See `paperpilot --help` for full options and Chinese/English output.

## 🧱 Development notes

- Keep run outputs and generated artifacts out of source control.
- Keep API keys out of git history.
- Prefer `.gitignore` over manual cleanup.
- Use semantic tags for releases and keep `README` + docs aligned.
- Keep `.github/workflows/*`, `RELEASING.md`, `CHANGELOG.md` in sync when publishing.

## 🧭 Open source checklist

- Ensure `~/.paperpilot/config.json`, `api.json`, and `.env` with credentials are never committed.
- Add/keep `LICENSE` and `.gitignore`.
- Add source code and tags before publishing release assets.
- Publish GitHub Pages from `docs/`.
- Keep versions in `pyproject.toml`, `literature_agent/__init__.py`, and generated manifests aligned.

### One-command release

```bash
# dry-run checks only
./scripts/release_everywhere.sh --dry-run

# normal release (pushed commit + tag + GH release + PyPI)
export PYPI_TOKEN='pypi-...'
./scripts/release_everywhere.sh

# release without publishing to PyPI
./scripts/release_everywhere.sh --no-pypi
```

Suggested publish flow (full):

```bash
python -m unittest discover -s tests
python -m compileall literature_agent
./publish_pypi.sh --dry-run --version <VERSION>
git add -A
git commit -m "chore: release v<VERSION>"
git tag -a v<VERSION> -m "v<VERSION>"
git push origin main --tags
./publish_pypi.sh --version <VERSION>
```

For GitHub Pages: enable Pages to deploy from `main` + `/docs`, or rely on `.github/workflows/gh-pages.yml`.

## 📚 Citation note

If you use PaperPilot in your work, include the repository URL and version used so results are reproducible.
