# Changelog

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
