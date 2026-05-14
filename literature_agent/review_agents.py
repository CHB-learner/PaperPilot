from __future__ import annotations

from typing import Any

from .models import CorpusItem, VerificationRecord


def run_review_agents(
    core_items: list[CorpusItem],
    final_items: list[CorpusItem],
    verification: list[VerificationRecord],
    canonical: dict[str, Any],
    evidence_ledger: dict[str, Any],
) -> dict[str, Any]:
    verification_by_key = {record.citation_key: record for record in verification}
    findings = [
        _source_verifier(final_items, verification_by_key),
        _relevance_judge(core_items, final_items),
        _citation_compliance(canonical, evidence_ledger),
        _devils_advocate(canonical, evidence_ledger),
    ]
    blocking = [issue for finding in findings for issue in finding["issues"] if finding["severity"] in {"high", "critical"}]
    return {
        "version": "1.4.0",
        "verdict": "needs_attention" if blocking else "pass",
        "agents": findings,
        "blocking_issues": blocking,
    }


def _source_verifier(items: list[CorpusItem], records: dict[str, VerificationRecord]) -> dict[str, Any]:
    issues = []
    for item in items:
        record = records.get(item.citation_key)
        if not record:
            issues.append(f"{item.citation_key}: missing verification record")
            continue
        if record.status == "needs_attention":
            issues.append(f"{item.citation_key}: {', '.join(record.issues) or 'verification needs attention'}")
    return {
        "agent": "SourceVerifierAgent",
        "severity": "high" if issues else "low",
        "checks": ["metadata verification", "url/pdf/code status"],
        "issues": issues,
        "recommendations": ["Review verification.json before citing unsupported claims."] if issues else [],
    }


def _relevance_judge(core_items: list[CorpusItem], final_items: list[CorpusItem]) -> dict[str, Any]:
    weak = [item for item in final_items if item.inclusion.score < 0.45]
    issues = [f"{item.citation_key}: low relevance score {item.inclusion.score:.2f}" for item in weak]
    if len(final_items) < max(3, min(5, len(core_items))):
        issues.append("Final report view is small; GitHub/code filtering may bias the synthesis.")
    return {
        "agent": "RelevanceJudgeAgent",
        "severity": "medium" if issues else "low",
        "checks": ["core corpus relevance", "final-view bias"],
        "issues": issues,
        "recommendations": ["Inspect excluded_papers.json and adjacent_papers.json if important papers look missing."] if issues else [],
    }


def _citation_compliance(canonical: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    labels = {paper.get("citation_label") for paper in canonical.get("papers", [])}
    issues = []
    for claim in ledger.get("claims", []):
        for citation in claim.get("citations", []):
            if citation not in labels:
                issues.append(f"{claim.get('claim_id')}: unknown citation {citation}")
        if claim.get("status") == "material_gap" and "MATERIAL GAP" not in str(claim.get("text")):
            issues.append(f"{claim.get('claim_id')}: evidence gap is not explicit in claim text")
    return {
        "agent": "CitationComplianceAgent",
        "severity": "high" if issues else "low",
        "checks": ["citation labels", "claim evidence status"],
        "issues": issues,
        "recommendations": ["Regenerate the report after fixing citation map or evidence ledger issues."] if issues else [],
    }


def _devils_advocate(canonical: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    issues = []
    papers = canonical.get("papers", [])
    if len(papers) < 5:
        issues.append("The final report has fewer than 5 papers, so method-level conclusions should be conservative.")
    gap_count = sum(1 for claim in ledger.get("claims", []) if claim.get("status") == "material_gap")
    if gap_count:
        issues.append(f"{gap_count} claims are marked as material gaps.")
    if canonical.get("quality_gate", {}).get("verdict") != "pass":
        issues.append("Quality gate did not pass; conclusions need extra caution.")
    return {
        "agent": "DevilsAdvocateAgent",
        "severity": "medium" if issues else "low",
        "checks": ["overclaiming risk", "small-corpus risk", "quality-gate risk"],
        "issues": issues,
        "recommendations": ["Treat broad trend claims as provisional unless supported by multiple cited papers."] if issues else [],
    }
