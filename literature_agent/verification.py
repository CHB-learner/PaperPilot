from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .models import CorpusItem, QualityGate, VerificationRecord


DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)


def verify_corpus(items: list[CorpusItem], download_log: list[dict]) -> list[VerificationRecord]:
    pdf_status_by_title = {str(item.get("title", "")): item for item in download_log}
    records: list[VerificationRecord] = []
    for item in items:
        paper = item.paper
        issues: list[str] = []
        doi_status = "not_available"
        if paper.doi:
            doi_status = "format_valid" if DOI_RE.match(paper.doi.strip()) else "format_invalid"
            if doi_status == "format_invalid":
                issues.append("invalid_doi_format")
        url_status = "present" if paper.url else "missing"
        if not paper.url:
            issues.append("missing_url")

        log = pdf_status_by_title.get(paper.title)
        if log:
            pdf_status = str(log.get("status") or "unknown")
        elif paper.pdf_url:
            pdf_status = "open_pdf_url_not_downloaded"
        else:
            pdf_status = "not_available"

        best_code = max((artifact.confidence for artifact in item.code_artifacts), default=0.0)
        if best_code >= 0.75:
            code_status = "high_confidence"
        elif best_code >= 0.55:
            code_status = "medium_confidence"
        elif item.code_artifacts:
            code_status = "low_confidence"
            issues.append("low_confidence_code_link")
        else:
            code_status = "not_available"

        status = "verified"
        if item.inclusion.label == "exclude":
            status = "excluded"
        elif issues:
            status = "plausible_with_warnings"
        elif doi_status == "not_available" and url_status == "missing":
            status = "unverified"
        records.append(
            VerificationRecord(
                citation_key=item.citation_key,
                title=paper.title,
                status=status,
                doi_status=doi_status,
                url_status=url_status,
                pdf_status=pdf_status,
                code_status=code_status,
                issues=issues,
            )
        )
    return records


def build_quality_gate(
    items: list[CorpusItem],
    final_items: list[CorpusItem],
    verification: list[VerificationRecord],
    download_log: list[dict],
    *,
    max_papers: int,
    github_filter: str,
    quality: str,
    dedup_stats: dict,
) -> QualityGate:
    total = len(items)
    core = [item for item in items if item.inclusion.label == "core"]
    adjacent = [item for item in items if item.inclusion.label == "adjacent"]
    excluded = [item for item in items if item.inclusion.label == "exclude"]
    downloaded = sum(1 for item in download_log if item.get("status") == "downloaded")
    with_pdf_url = sum(1 for item in core if item.paper.pdf_url)
    with_code = sum(1 for item in core if item.paper.has_code or item.code_artifacts)
    recent = sum(1 for item in core if item.paper.year and item.paper.year >= 2021)
    source_counts = Counter(source for item in core for source in (item.paper.sources or [item.paper.source]))
    warning_count = sum(1 for record in verification if record.status == "plausible_with_warnings")
    metrics: dict[str, Any] = {
        "total_candidates": total,
        "core_count": len(core),
        "adjacent_count": len(adjacent),
        "excluded_count": len(excluded),
        "final_report_count": len(final_items),
        "core_ratio": round(len(core) / total, 4) if total else 0,
        "pdf_url_coverage": round(with_pdf_url / len(core), 4) if core else 0,
        "pdf_downloaded": downloaded,
        "code_coverage": round(with_code / len(core), 4) if core else 0,
        "recent_core_count": recent,
        "source_counts": dict(sorted(source_counts.items())),
        "verification_warnings": warning_count,
        "dedup": dedup_stats,
        "github_filter": github_filter,
        "quality": quality,
    }

    strictness = {"fast": 5, "balanced": 8, "strict": 12}.get(quality, 8)
    issues: list[str] = []
    recommendations: list[str] = []
    if len(core) < min(strictness, max_papers):
        issues.append("too_few_core_papers")
        recommendations.append("Broaden search queries or relax code filtering in the final view.")
    if total and len(excluded) / total > 0.35:
        issues.append("high_off_topic_rate")
        recommendations.append("Refine negative keywords and source-specific search strings.")
    if core and with_pdf_url / len(core) < 0.25:
        issues.append("low_open_pdf_coverage")
        recommendations.append("Use Unpaywall email or inspect publisher/preprint pages manually.")
    if github_filter == "required" and len(final_items) < min(5, max_papers):
        issues.append("github_filter_too_strict")
        recommendations.append("Use github_filter=any for a fuller scholarly corpus, then inspect code table separately.")
    if warning_count > max(3, len(core) // 3):
        issues.append("many_verification_warnings")
        recommendations.append("Review DOI, URL, and code confidence warnings before citing.")

    if "too_few_core_papers" in issues or "github_filter_too_strict" in issues:
        verdict = "retry"
    elif issues and quality == "strict":
        verdict = "needs_user_attention"
    else:
        verdict = "pass"
    return QualityGate(verdict=verdict, metrics=metrics, issues=issues, recommendations=recommendations)


def verification_to_dict(records: list[VerificationRecord]) -> list[dict]:
    return [record.to_dict() for record in records]
