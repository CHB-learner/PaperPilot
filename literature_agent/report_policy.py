from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import CorpusItem


MIN_REPORT_PAPERS = 30


@dataclass
class ReportSelection:
    items: list[CorpusItem]
    stats: dict[str, Any]
    shortfall: dict[str, Any] | None = None


def validate_report_paper_bounds(max_papers: int, min_report_papers: int = MIN_REPORT_PAPERS) -> tuple[bool, str]:
    if min_report_papers < MIN_REPORT_PAPERS:
        return False, f"--min-report-papers must be at least {MIN_REPORT_PAPERS}."
    if max_papers < min_report_papers:
        return False, f"--max-papers must be at least --min-report-papers ({min_report_papers})."
    return True, ""


def select_report_items(
    core_items: list[CorpusItem],
    adjacent_items: list[CorpusItem],
    github_filter: str,
    *,
    max_papers: int,
    min_report_papers: int = MIN_REPORT_PAPERS,
) -> ReportSelection:
    selected: list[CorpusItem] = []
    seen: set[str] = set()
    stats: dict[str, Any] = {
        "min_report_papers": min_report_papers,
        "max_papers": max_papers,
        "core_available": len(core_items),
        "adjacent_available": len(adjacent_items),
        "core_report_count": 0,
        "adjacent_report_count": 0,
        "minimum_fill_count": 0,
        "code_filter_fallback_count": 0,
        "adjacent_fill_count": 0,
        "final_report_count": 0,
        "github_filter": github_filter,
        "selection_policy": "core_first_then_code_fallback_then_adjacent_fill",
    }

    def add(items: list[CorpusItem], role: str, reason: str) -> None:
        for item in items:
            if len(selected) >= max_papers:
                break
            if item.citation_key in seen:
                continue
            _mark_report_role(item, role, reason)
            selected.append(item)
            seen.add(item.citation_key)

    core_matching, core_not_matching = _partition_by_filter(core_items, github_filter)
    adjacent_matching, adjacent_not_matching = _partition_by_filter(adjacent_items, github_filter)

    add(core_matching, "core", "Core paper satisfying the requested code filter.")
    add(core_not_matching, "code_filter_fallback", "Core paper retained to meet the minimum report size despite the code filter.")
    if len(selected) < min_report_papers:
        add(adjacent_matching, "adjacent_fill", "Adjacent paper satisfying the requested code filter, used to meet the minimum report size.")
    if len(selected) < min_report_papers:
        add(adjacent_not_matching, "minimum_fill", "Adjacent paper used to meet the minimum report size.")
    if len(selected) < max_papers:
        add(adjacent_matching + adjacent_not_matching, "adjacent_overflow", "Additional adjacent paper included below max_papers.")

    stats.update(_selection_counts(selected))
    stats["final_report_count"] = len(selected)

    if len(selected) < min_report_papers:
        shortfall = {
            "verdict": "needs_user_attention",
            "min_report_papers": min_report_papers,
            "final_report_count": len(selected),
            "missing_count": min_report_papers - len(selected),
            "core_available": len(core_items),
            "adjacent_available": len(adjacent_items),
            "reason": "Fewer than the minimum required core/adjacent papers were available after screening.",
            "recommendations": [
                "Broaden the topic or increase source coverage.",
                "Relax code filtering if github_filter=required.",
                "Add a local corpus with --user-corpus.",
            ],
        }
        return ReportSelection(selected, stats, shortfall)
    return ReportSelection(selected, stats)


def _selection_counts(items: list[CorpusItem]) -> dict[str, int]:
    counts = {
        "core_report_count": 0,
        "adjacent_report_count": 0,
        "minimum_fill_count": 0,
        "code_filter_fallback_count": 0,
        "adjacent_fill_count": 0,
    }
    for item in items:
        role = str((item.paper.raw or {}).get("report_role") or "")
        if role in {"core", "code_filter_fallback"}:
            counts["core_report_count"] += 1
        if role in {"adjacent_fill", "minimum_fill", "adjacent_overflow"}:
            counts["adjacent_report_count"] += 1
        if role == "minimum_fill":
            counts["minimum_fill_count"] += 1
        if role == "code_filter_fallback":
            counts["code_filter_fallback_count"] += 1
        if role == "adjacent_fill":
            counts["adjacent_fill_count"] += 1
    return counts


def _partition_by_filter(items: list[CorpusItem], github_filter: str) -> tuple[list[CorpusItem], list[CorpusItem]]:
    matching: list[CorpusItem] = []
    not_matching: list[CorpusItem] = []
    for item in items:
        (matching if _matches_code_filter(item, github_filter) else not_matching).append(item)
    return matching, not_matching


def _matches_code_filter(item: CorpusItem, github_filter: str) -> bool:
    has_code = item.paper.has_code or bool(item.code_artifacts) or bool(item.paper.github_url or item.paper.code_url)
    if github_filter == "required":
        return has_code
    if github_filter == "none":
        return not has_code
    return True


def _mark_report_role(item: CorpusItem, role: str, reason: str) -> None:
    item.paper.raw.setdefault("report_role", role)
    item.paper.raw.setdefault("report_selection_reason", reason)
    item.paper.raw.setdefault("report_tier", "core" if role in {"core", "code_filter_fallback"} else "adjacent")
