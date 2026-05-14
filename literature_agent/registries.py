from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


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
    ToolManifest("pdf_downloader", "pdf", "Open-access PDF download without paywall bypass.", ["Paper[]"], ["download_log.json", "pdfs/"]),
    ToolManifest("fulltext_parser", "pdf", "Extract text from downloaded PDFs.", ["download_log.json"], ["fulltext/", "paper_notes.json"]),
    ToolManifest("report_renderer", "report", "Render canonical report to Markdown, HTML, and PDF.", ["report.canonical.json"], ["report.zh.*", "report.en.*"]),
]


CAPABILITIES = [
    CapabilityManifest(
        "literature_review",
        "Default AI literature review workflow.",
        ["intake", "protocol", "search", "corpus", "screening", "verification", "synthesis", "review", "report"],
        ["keyword", "LLM config"],
        ["report.canonical.json", "report.zh.md", "report.en.md", "report.zh.html", "report.en.html", "report.zh.pdf", "report.en.pdf"],
        ["quality_gate", "review_agent_checks", "evidence_ledger"],
    ),
    CapabilityManifest(
        "systematic_review",
        "Stricter review mode with PRISMA-style accounting and stronger quality gates.",
        ["intake", "protocol", "search", "corpus", "screening", "verification", "synthesis", "review", "report"],
        ["keyword", "--mode systematic"],
        ["quality_gate.json", "evidence_ledger.json", "report.*"],
        ["source_verification", "citation_compliance"],
    ),
    CapabilityManifest(
        "code_reproducibility_review",
        "Assess whether papers have trustworthy public implementations.",
        ["corpus", "verification", "review"],
        ["corpus.json", "verification.json"],
        ["review_agent_findings.json"],
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


def registry_manifest() -> dict[str, Any]:
    return {
        "tool_registry_version": "1.1.0",
        "capability_registry_version": "1.1.0",
        "tools": [asdict(tool) for tool in TOOLS],
        "capabilities": [asdict(capability) for capability in CAPABILITIES],
    }
