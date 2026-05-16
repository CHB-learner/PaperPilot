from __future__ import annotations

from .models import ResearchProtocol, SearchPlan
from .openai_client import OpenAIClient
from .prompts import run_prompt_json
from .query import QueryUnderstanding
from .sources import SOURCE_SPECS


DEFAULT_SOURCES = [
    "arxiv",
    "semantic_scholar",
    "openalex",
    "crossref",
    "openreview",
    "pubmed",
    "europe_pmc",
    "biorxiv",
    "medrxiv",
    "dblp",
    "acl_anthology",
]


def build_protocol(
    understanding: QueryUnderstanding,
    plan: SearchPlan,
    github_filter: str,
    client: OpenAIClient | None,
) -> ResearchProtocol:
    fallback = _fallback_protocol(understanding, plan, github_filter)
    if not client or not client.available:
        return fallback
    payload = run_prompt_json(
        client,
        "protocol",
        fallback=fallback.to_dict(),
        understanding=understanding.to_markdown(),
        plan=plan.to_dict(),
    )
    return ResearchProtocol(
        research_question=str(payload.get("research_question") or fallback.research_question),
        scope=_as_list(payload.get("scope"), fallback.scope)[:8],
        inclusion_criteria=_as_list(payload.get("inclusion_criteria"), fallback.inclusion_criteria)[:10],
        exclusion_criteria=_as_list(payload.get("exclusion_criteria"), fallback.exclusion_criteria)[:10],
        negative_keywords=_as_list(payload.get("negative_keywords"), fallback.negative_keywords)[:20],
        search_sources=_filter_search_sources(_as_list(payload.get("search_sources"), fallback.search_sources)[:20]) or DEFAULT_SOURCES,
        since_year=plan.since_year,
        github_filter=github_filter,
        pdf_policy=fallback.pdf_policy,
        notes=_as_list(payload.get("notes"), fallback.notes)[:8],
    )


def _filter_search_sources(source_names: list[str]) -> list[str]:
    return [name for name in source_names if name in SOURCE_SPECS]


def _fallback_protocol(
    understanding: QueryUnderstanding,
    plan: SearchPlan,
    github_filter: str,
) -> ResearchProtocol:
    query = plan.recommended_query or understanding.original_keyword
    negative = [
        "docking",
        "molecular docking",
        "rna-seq",
        "quality control",
        "alignment tool",
        "data sharing",
        "aptamer protein interaction",
        "fingerprint library",
        "biosensor wet lab only",
    ]
    return ResearchProtocol(
        research_question=f"What are the main methods, evidence, code resources, and limitations for {query}?",
        scope=understanding.included_scope
        or [
            "Computational and AI methods directly addressing the user topic",
            "Recent papers, benchmarks, and code resources",
            "Adjacent methods only when they explain the core task",
        ],
        inclusion_criteria=[
            "The paper directly studies the requested task or a core subtask.",
            "The paper reports a computational method, benchmark, dataset, survey, or analysis relevant to the task.",
            "The title or abstract contains topic-specific terminology, not only generic field terminology.",
            "Recent papers are prioritized while foundational work may be retained when methodologically important.",
        ],
        exclusion_criteria=[
            "Purely experimental or clinical studies without a computational method.",
            "Generic bioinformatics platforms not centered on the requested task.",
            "Papers about adjacent biological data processing that do not address design, generation, prediction, or evaluation for the topic.",
            "Repository links that are generic tools rather than the paper implementation should not make a paper core.",
        ],
        negative_keywords=negative,
        search_sources=DEFAULT_SOURCES,
        since_year=plan.since_year,
        github_filter=github_filter,
        notes=[
            "GitHub filtering is treated as a final report view, not as a corpus inclusion criterion.",
            "Open PDFs are downloaded only when clearly available.",
        ],
    )


def _as_list(value, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return list(fallback)
