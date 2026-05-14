from __future__ import annotations

import re
from typing import Any


def build_evidence_ledger(canonical: dict[str, Any], literature_matrix: list[dict[str, Any]]) -> dict[str, Any]:
    paper_by_key = {paper["citation_key"]: paper for paper in canonical.get("papers", [])}
    matrix_by_key = {row.get("citation_key"): row for row in literature_matrix}
    claims: list[dict[str, Any]] = []

    overview = canonical.get("field_overview") or {}
    for key in ["background", "problem_definition", "why_it_matters", "scope_note"]:
        text = str(overview.get(key) or "").strip()
        if text:
            claims.append(_claim(f"field_overview.{key}", text, _all_refs(paper_by_key), "moderate", "synthesis"))

    for method in canonical.get("method_taxonomy", []):
        refs = _refs_from_labels(method.get("representative_paper_refs", []), paper_by_key)
        text = " ".join(
            str(method.get(part) or "")
            for part in ["name", "core_idea", "typical_pipeline"]
            if method.get(part)
        ).strip()
        claims.append(_claim(f"method_taxonomy.{method.get('name', 'method')}", text or "MATERIAL GAP", refs, _strength(refs), "method_taxonomy"))

    for summary in canonical.get("paper_summaries", []):
        key = summary.get("citation_key")
        paper = paper_by_key.get(key)
        refs = [paper["citation_label"]] if paper else []
        row = matrix_by_key.get(key, {})
        claims.append(
            _claim(
                f"paper_summary.{key}",
                str(summary.get("summary") or "MATERIAL GAP"),
                refs,
                "strong" if row.get("evidence_basis") == "fulltext+metadata" else "limited",
                row.get("evidence_basis") or summary.get("evidence_basis") or "metadata_or_abstract_only",
            )
        )

    for idx, trend in enumerate(canonical.get("research_trends", []), start=1):
        claims.append(_claim(f"research_trend.{idx}", str(trend), _all_refs(paper_by_key), "moderate", "synthesis"))

    return {
        "version": "1.2.0",
        "policy": "Each report-level claim should be tied to paper citations or marked MATERIAL GAP when evidence is insufficient.",
        "claim_count": len(claims),
        "claims": claims,
    }


def _claim(claim_id: str, text: str, citations: list[str], strength: str, evidence_basis: str) -> dict[str, Any]:
    unsupported = not citations or "MATERIAL GAP" in text
    return {
        "claim_id": claim_id,
        "text": text,
        "citations": citations,
        "evidence_strength": "gap" if unsupported else strength,
        "evidence_basis": evidence_basis,
        "status": "material_gap" if unsupported else "grounded",
    }


def _all_refs(paper_by_key: dict[str, dict[str, Any]], limit: int = 8) -> list[str]:
    return [paper["citation_label"] for paper in list(paper_by_key.values())[:limit]]


def _refs_from_labels(labels: list[str], paper_by_key: dict[str, dict[str, Any]]) -> list[str]:
    valid = {paper["citation_label"] for paper in paper_by_key.values()}
    refs = []
    for label in labels or []:
        match = re.match(r"(\[\d+\])", str(label).strip())
        if match and match.group(1) in valid:
            refs.append(match.group(1))
    return list(dict.fromkeys(refs))


def _strength(refs: list[str]) -> str:
    if len(refs) >= 4:
        return "strong"
    if len(refs) >= 2:
        return "moderate"
    if refs:
        return "limited"
    return "gap"
