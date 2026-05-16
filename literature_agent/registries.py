from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .sources import SourceConfig, source_manifest


@dataclass(frozen=True)
class ToolManifest:
    name: str
    layer: str
    description: str
    inputs: list[str]
    outputs: list[str]
    deterministic: bool = True


@dataclass(frozen=True)
class CapabilityManifest:
    name: str
    description: str
    stages: list[str]
    inputs: list[str]
    outputs: list[str]
    quality_gates: list[str]


TOOLS = [
    ToolManifest("arxiv", "search", "arXiv metadata and open PDF lookup.", ["query", "since_year"], ["Paper[]"]),
    ToolManifest("semantic_scholar", "search", "Semantic Scholar metadata, citation, and open PDF lookup.", ["query", "since_year"], ["Paper[]"]),
    ToolManifest("openalex", "search", "OpenAlex work metadata and open-access links.", ["query", "since_year"], ["Paper[]"]),
    ToolManifest("crossref", "search", "Crossref DOI and venue metadata.", ["query", "since_year"], ["Paper[]"]),
    ToolManifest("openreview", "search", "OpenReview paper search and PDF links.", ["query", "since_year"], ["Paper[]"]),
    ToolManifest("github_resolver", "code", "Repository extraction and optional GitHub search.", ["Paper[]"], ["CodeArtifact[]"]),
    ToolManifest("pdf_downloader", "pdf", "Open-access PDF download without paywall bypass.", ["Paper[]"], ["verification/download_log.json", "assets/pdfs/"]),
    ToolManifest("fulltext_parser", "pdf", "Extract text from downloaded PDFs.", ["verification/download_log.json"], ["assets/fulltext/", "verification/paper_notes.json"]),
    ToolManifest("report_renderer", "report", "Render canonical report to Markdown, HTML, and PDF.", ["reports/report.canonical.json"], ["reports/report.zh.*", "reports/report.en.*"]),
    ToolManifest("obsidian_wiki_renderer", "report", "Render the canonical report into an Obsidian wikilink knowledge graph.", ["reports/report.canonical.json"], ["wiki/obsidian/"]),
]


CAPABILITIES = [
    CapabilityManifest(
        "literature_review",
        "Default AI literature review workflow.",
        ["intake", "protocol", "search", "corpus", "screening", "verification", "synthesis", "review", "report"],
        ["keyword", "LLM config"],
        ["reports/report.canonical.json", "reports/report.zh.md", "reports/report.en.md", "reports/report.zh.html", "reports/report.en.html", "reports/report.zh.pdf", "reports/report.en.pdf", "wiki/obsidian/"],
        ["quality_gate", "review_agent_checks", "evidence_ledger"],
    ),
    CapabilityManifest(
        "systematic_review",
        "Stricter review mode with PRISMA-style accounting and stronger quality gates.",
        ["intake", "protocol", "search", "corpus", "screening", "verification", "synthesis", "review", "report"],
        ["keyword", "--mode systematic"],
        ["verification/quality_gate.json", "verification/evidence_ledger.json", "reports/report.*"],
        ["source_verification", "citation_compliance"],
    ),
    CapabilityManifest(
        "code_reproducibility_review",
        "Assess whether papers have trustworthy public implementations.",
        ["corpus", "verification", "review"],
        ["corpus/corpus.json", "verification/verification.json"],
        ["verification/review_agent_findings.json"],
        ["code_confidence"],
    ),
    CapabilityManifest(
        "topic_monitoring",
        "Reserved capability for future recurring literature monitoring.",
        ["intake", "search", "screening", "report"],
        ["keyword", "schedule"],
        ["digest"],
        ["source_verification"],
    ),
]


def registry_manifest(source_configs: dict[str, SourceConfig] | None = None) -> dict[str, Any]:
    return {
        "tool_registry_version": "1.2.0",
        "capability_registry_version": "1.2.0",
        "tools": [asdict(tool) for tool in TOOLS],
        "sources": source_manifest(source_configs),
        "capabilities": [asdict(capability) for capability in CAPABILITIES],
    }
