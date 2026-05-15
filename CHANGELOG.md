# Changelog

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
