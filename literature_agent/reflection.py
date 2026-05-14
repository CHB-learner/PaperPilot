from __future__ import annotations

from .models import Paper, SearchPlan
from .openai_client import OpenAIClient
from .prompts import run_prompt_json


def reflect(
    papers: list[Paper],
    plan: SearchPlan,
    download_log: list[dict],
    github_filter: str,
    client: OpenAIClient | None,
) -> dict:
    downloaded = sum(1 for item in download_log if item.get("status") == "downloaded")
    with_pdf = sum(1 for paper in papers if paper.pdf_url)
    with_code = sum(1 for paper in papers if paper.has_code)
    recent = sum(1 for paper in papers if paper.year and plan.since_year and paper.year >= plan.since_year)
    issues: list[str] = []
    if len(papers) < min(10, plan.max_papers):
        issues.append("too_few_papers")
    if plan.since_year and recent < max(3, len(papers) // 3):
        issues.append("too_few_recent_papers")
    if papers and with_pdf / len(papers) < 0.25:
        issues.append("low_pdf_coverage")
    if github_filter == "required" and len(papers) < min(5, plan.max_papers):
        issues.append("github_filter_too_strict")
    elif papers and with_code / len(papers) < 0.2:
        issues.append("low_code_coverage")

    improved_queries = []
    if issues:
        improved_queries = [
            f"{plan.recommended_query} survey",
            f"{plan.recommended_query} github",
            f"{plan.recommended_query} benchmark",
            f"{plan.recommended_query} arxiv",
        ]

    result = {
        "paper_count": len(papers),
        "papers_with_pdf_url": with_pdf,
        "pdfs_downloaded": downloaded,
        "papers_with_code": with_code,
        "github_filter": github_filter,
        "issues": issues,
        "should_retry": bool(issues and improved_queries),
        "improved_queries": improved_queries,
        "notes": [],
    }
    if client and client.available:
        try:
            llm = run_prompt_json(
                client,
                "reflection",
                fallback=result,
                plan=plan.to_dict(),
                metrics=result,
            )
            result["issues"] = _as_list(llm.get("issues"), result["issues"])
            result["should_retry"] = bool(llm.get("should_retry", result["should_retry"]))
            result["improved_queries"] = _as_list(llm.get("improved_queries"), result["improved_queries"])[:4]
            result["notes"] = _as_list(llm.get("notes"), [])
        except Exception as exc:
            result["notes"].append(f"LLM reflection failed: {exc}")
    return result


def _as_list(value, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return fallback
