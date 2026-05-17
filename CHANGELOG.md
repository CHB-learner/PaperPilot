# Changelog

## [Unreleased]

### Changed
- Promoted the Cloudflare Workers online demo as the primary hosted browser experience.
- Updated public documentation and website links to use `https://paperpilot.aleck-757.workers.dev/`.
- Documented Workers + Assets deployment through `wrangler.jsonc` and `/api/literature-search`.

### Fixed
- Added OpenAlex/Crossref fallback search and source diagnostics for the online demo.
- Treat `LLM_API_KEY=123456` as an unconfigured placeholder instead of calling the LLM provider with a dummy key.

## [1.6.0] - 2026-05-16

### Added
- Added the hosted online experience for LLM-planned public literature search.
- Added lightweight Markdown and HTML report downloads in the browser demo.
- Documented the hosted online demo and DeepSeek OpenAI-compatible environment configuration.

### Changed
- Switched the online demo defaults to DeepSeek `deepseek-v4-flash`.
- Updated online search result count options to 10, 30, and 50 papers.

## [1.5.3] - 2026-05-15

### Changed
- Removed the default 30-paper minimum gate for formal reports.
- Changed the default final report cap to 100 papers.
- Kept `--min-report-papers` as an optional user-controlled minimum; default is now `0`.
- Updated README, Chinese README, project homepage, quality gate, and report wording for the new report-size policy.

## [1.5.2] - 2026-05-15

### Changed
- Updated README, Chinese README, and project homepage wording to describe PaperPilot as a broader scholarly literature review agent for AI, biomedicine, and AI for Science.

## [1.5.1] - 2026-05-15

### Fixed
- Fixed non-RNA / non-AI biomedical topics being over-screened to zero papers.
- Fixed query understanding prompts that could silently narrow broad biomedical requests into AI-only protocols.
- Replaced the RNA-specific screening gate with topic-adaptive relevance scoring while preserving RNA inverse-folding exclusions.
- Fixed the interactive welcome banner to show the package version dynamically instead of stale `v1.3`.

## [1.5.0] - 2026-05-15

### Added
- Added a formal 30-paper minimum policy for generated literature reports.
- Added `--min-report-papers` and `--no-obsidian-wiki` CLI options.
- Added `report_selection.json` and `shortfall.json` diagnostics for minimum-report enforcement.
- Added default Obsidian Wiki export under `obsidian_wiki/` with paper, method, topic, claim, manifest, and lint files.

### Changed
- Final report selection is now core-first, then code-filter fallback, then adjacent-paper fill when needed.
- Quality gate metrics now record minimum-report counts, fill counts, and code-filter fallback counts.
- README, Chinese README, local usage docs, and project homepage now document the 30-paper policy and Obsidian Wiki output.

## [1.4.5] - 2026-05-15

### Added
- Release infrastructure refinement: `scripts/release_everywhere.sh` now supports end-to-end local validation + dry-run with clean push/PyPI gating.
- CLI/docs alignment clean-up: release helper examples now use version placeholders and avoid stale manual version pinning in docs.
- Publishing workflow polish: stable dry-run behavior and deterministic changelog extraction for GitHub release notes.

### Changed
- Updated version tracking to keep `pyproject.toml` and `literature_agent/__init__.py` in sync during one-command release flows.
- Improved release safety: skip-push / no-pypi / dry-run semantics are now consistently applied across publishing stages.

## [1.4.4] - 2026-05-15

### Added
- Added multi-source registry expansion with `papers.cool` and `deepxiv` integration.
- Added citation-numbered canonical reporting flow with consistent `zh/en/html/pdf` outputs and evidence mapping.
- Added stronger workflow observability: richer run artifacts, source diagnostics, evidence ledger flow and doctor checks.
- Added prompt registry improvements and synthesis depth enhancements (RQ framing, method taxonomy, claims/evidence map, contradiction tracking).
- Added default `~/.paperpilot/config.json` initialization behavior and optional source API slots in config templates.
- Added GitHub homepage content under `docs/` for project promotion.

### Changed
- Upgraded report synthesis pipeline to produce deeper review-style text (background, methods, evidence, trends, gaps).
- Improved paper normalization and ranking robustness for mixed-type metadata.
- Fixed citation manifest alignment and report table rendering stability.

### Fixed
- Fixed evidence ledger generation edge cases when claim IDs are absent.
- Fixed `workflow` manifest version drift by binding to package version.
- Fixed rank/synthesis pipeline compatibility with non-string metadata inputs.

## [1.4.3] - 2026-05-13

- Added source management commands and interactive `/sources` command.
- Added doctor workflow and richer CLI presentation.

## [Unreleased]

- Follow-up hardening for source parsers and source-specific failure diagnostics.
