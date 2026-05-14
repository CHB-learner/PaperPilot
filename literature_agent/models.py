from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Paper:
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    abstract: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    openreview_id: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    citation_count: int | None = None
    source: str = "unknown"
    sources: list[str] = field(default_factory=list)
    has_code: bool = False
    github_url: str | None = None
    code_url: str | None = None
    code_source: str | None = None
    relevance_score: float = 0.0
    rank_score: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.title = _metadata_text(self.title)
        self.authors = [_metadata_text(author) for author in self.authors if _metadata_text(author)]
        self.venue = _metadata_text(self.venue) or None
        self.abstract = _metadata_text(self.abstract) or None
        self.doi = _metadata_text(self.doi) or None
        self.arxiv_id = _metadata_text(self.arxiv_id) or None
        self.openreview_id = _metadata_text(self.openreview_id) or None
        self.url = _metadata_text(self.url) or None
        self.pdf_url = _metadata_text(self.pdf_url) or None
        self.source = _metadata_text(self.source) or "unknown"
        self.sources = [_metadata_text(source) for source in self.sources if _metadata_text(source)]
        self.github_url = _metadata_text(self.github_url) or None
        self.code_url = _metadata_text(self.code_url) or None
        self.code_source = _metadata_text(self.code_source) or None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sources"] = sorted(set(self.sources or [self.source]))
        return data


@dataclass
class SearchPlan:
    original_keyword: str
    recommended_query: str
    search_queries: list[str]
    subtopics: list[str]
    since_year: int | None
    max_papers: int
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchProtocol:
    research_question: str
    scope: list[str]
    inclusion_criteria: list[str]
    exclusion_criteria: list[str]
    negative_keywords: list[str]
    search_sources: list[str]
    since_year: int | None
    github_filter: str
    pdf_policy: str = "download_open_access_only"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CodeArtifact:
    url: str
    kind: str = "unknown"
    source: str = "metadata"
    confidence: float = 0.0
    confidence_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InclusionDecision:
    label: str
    score: float
    reason: str
    matched_terms: list[str] = field(default_factory=list)
    negative_hits: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CorpusItem:
    citation_key: str
    paper: Paper
    inclusion: InclusionDecision
    code_artifacts: list[CodeArtifact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_key": self.citation_key,
            "paper": self.paper.to_dict(),
            "inclusion": self.inclusion.to_dict(),
            "code_artifacts": [artifact.to_dict() for artifact in self.code_artifacts],
        }


@dataclass
class VerificationRecord:
    citation_key: str
    title: str
    status: str
    doi_status: str = "not_available"
    url_status: str = "not_checked"
    pdf_status: str = "not_available"
    code_status: str = "not_available"
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QualityGate:
    verdict: str
    metrics: dict[str, Any]
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _metadata_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("display_name", "name", "title", "value", "text"):
            if value.get(key):
                return _metadata_text(value.get(key))
        return " ".join(_metadata_text(item) for item in value.values() if _metadata_text(item)).strip()
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_metadata_text(item) for item in value if _metadata_text(item)).strip()
    return str(value).strip()
