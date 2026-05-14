from __future__ import annotations

from dataclasses import dataclass
from string import Template
from typing import Any


@dataclass(frozen=True)
class PromptSpec:
    prompt_id: str
    version: str
    role: str
    description: str
    instructions: str
    template: str
    required_keys: tuple[str, ...] = ()

    def render(self, **values: Any) -> str:
        return Template(self.template).safe_substitute({key: _stringify(value) for key, value in values.items()})

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "prompt_id": self.prompt_id,
            "version": self.version,
            "role": self.role,
            "description": self.description,
            "required_keys": list(self.required_keys),
        }


PROMPTS: dict[str, PromptSpec] = {
    "query_understanding": PromptSpec(
        prompt_id="query_understanding",
        version="1.1.0",
        role="QueryUnderstandingAgent",
        description="Parse user research intent, ambiguity, scope, and diversified search terms.",
        instructions="You are a research query understanding agent. Return only valid JSON.",
        required_keys=(
            "original_keyword",
            "recommended_query",
            "possible_interpretations",
            "included_scope",
            "excluded_scope",
            "search_terms",
            "needs_confirmation",
            "rationale",
        ),
        template="""
Analyze this literature-search keyword for an AI-related paper search agent: $keyword

Return JSON with these keys:
original_keyword, recommended_query, possible_interpretations, included_scope,
excluded_scope, search_terms, needs_confirmation, rationale.

If the keyword is broad or ambiguous, set needs_confirmation=true. Prefer AI-related
interpretations but mention important non-AI ambiguity.
""",
    ),
    "planner": PromptSpec(
        prompt_id="planner",
        version="1.1.0",
        role="PlannerAgent",
        description="Turn query understanding into English search strings, subtopics, and source strategy notes.",
        instructions="You are a literature-search planning agent. Return only valid JSON.",
        required_keys=("recommended_query", "search_queries", "subtopics", "notes"),
        template="""
Create a search plan for this query understanding:
$understanding

Return JSON:
{
  "recommended_query": "...",
  "search_queries": ["..."],
  "subtopics": ["..."],
  "notes": ["..."]
}

Use English search strings. Include searches for classic papers, recent progress,
surveys, and papers likely to have code.
""",
    ),
    "protocol": PromptSpec(
        prompt_id="protocol",
        version="1.1.0",
        role="ResearchProtocolAgent",
        description="Create screening protocol, criteria, negative keywords, and source plan.",
        instructions="You are a research protocol agent. Return only valid JSON.",
        required_keys=(
            "research_question",
            "scope",
            "inclusion_criteria",
            "exclusion_criteria",
            "negative_keywords",
            "search_sources",
            "notes",
        ),
        template="""
Create a concise literature-review protocol from this query understanding and search plan.

Query understanding:
$understanding

Search plan:
$plan

The protocol must be specific enough to screen papers automatically.
Return JSON with keys:
research_question, scope, inclusion_criteria, exclusion_criteria,
negative_keywords, search_sources, notes.
Use English for criteria and keywords.
""",
    ),
    "screening": PromptSpec(
        prompt_id="screening",
        version="1.1.0",
        role="RelevanceJudgeAgent",
        description="Classify uncertain corpus entries as core, adjacent, or exclude.",
        instructions="You are a strict literature screening agent. Return only valid JSON.",
        required_keys=("decisions",),
        template="""
Classify each paper for the research question. Labels: core, adjacent, exclude.
Use core only for papers directly about the requested task. Use exclude for generic tools.

Input JSON:
$payload

Return JSON:
{"decisions":[{"citation_key":"...", "label":"core|adjacent|exclude", "score":0.0, "reason":"..."}]}
""",
    ),
    "synthesis": PromptSpec(
        prompt_id="synthesis",
        version="1.1.0",
        role="SynthesisAgent",
        description="Generate evidence-bounded field overview, taxonomy, summaries, comparison, trends, and gaps.",
        instructions="You are an evidence synthesis agent. Return only valid JSON.",
        required_keys=(
            "field_overview",
            "method_taxonomy",
            "paper_summaries",
            "method_comparison",
            "research_trends",
            "knowledge_gaps",
        ),
        template="""
Synthesize this verified literature corpus. Use only the provided matrix.
If a claim is not supported by the matrix, write MATERIAL GAP.

Input JSON:
$payload

Return JSON with:
{
  "field_overview": {"background":"...", "problem_definition":"...", "why_it_matters":"...", "scope_note":"..."},
  "method_evolution": ["..."],
  "themes": [{"name":"...", "evidence_strength":"Strong|Moderate|Emerging", "citation_keys":["..."], "summary":"...", "core_idea":"...", "typical_pipeline":"...", "strengths":["..."], "limitations":["..."]}],
  "method_taxonomy": [{"name":"...", "core_idea":"...", "typical_pipeline":"...", "representative_papers":["citation_key"], "strengths":["..."], "limitations":["..."]}],
  "paper_summaries": [{"citation_key":"...", "title":"...", "summary":"...", "method_category":"...", "evidence_basis":"..."}],
  "method_comparison": [{"method_category":"...", "input":"...", "output":"...", "algorithm_pattern":"...", "typical_metrics":"...", "best_for":"...", "limitations":"...", "representative_papers":["citation_key"]}],
  "research_trends": ["..."],
  "contradictions": ["..."],
  "knowledge_gaps": ["..."],
  "follow_up_keywords": ["..."],
  "limitations": ["..."]
}
""",
    ),
    "abstract": PromptSpec(
        prompt_id="abstract",
        version="1.1.0",
        role="ReportAbstractAgent",
        description="Write matched Chinese and English APA-style abstracts.",
        instructions="You write concise bilingual APA-style abstracts. Return only valid JSON.",
        required_keys=("zh", "en"),
        template="""
Write matching Chinese and English abstracts from this canonical report summary.
Do not add claims that are absent from the provided summary.
Summary:
title=$title
prisma=$prisma
themes=$themes
field_overview=$field_overview
limitations=$limitations

Return JSON: {"zh":"...", "en":"..."}
""",
    ),
    "reflection": PromptSpec(
        prompt_id="reflection",
        version="1.1.0",
        role="ReflectionAgent",
        description="Assess corpus quality and propose retry queries when needed.",
        instructions="You are a literature-search quality reflection agent. Return only valid JSON.",
        required_keys=("issues", "should_retry", "improved_queries", "notes"),
        template="""
Assess this search result quality.
Plan: $plan
Metrics: $metrics

Return JSON with keys: issues, should_retry, improved_queries, notes.
Keep improved_queries as English search strings.
""",
    ),
}


def get_prompt(prompt_id: str) -> PromptSpec:
    return PROMPTS[prompt_id]


def prompt_manifest() -> list[dict[str, Any]]:
    return [prompt.manifest_entry() for prompt in PROMPTS.values()]


def run_prompt_json(client, prompt_id: str, fallback: dict[str, Any], **values: Any) -> dict[str, Any]:
    prompt = get_prompt(prompt_id)
    result = client.json(prompt.instructions, prompt.render(**values), fallback=fallback)
    if _missing_required(result, prompt.required_keys):
        # One deterministic fallback keeps malformed LLM output from poisoning downstream stages.
        merged = dict(fallback)
        merged.update({key: value for key, value in result.items() if value not in (None, "", [], {})})
        return merged
    return result


def _missing_required(result: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(key not in result or result[key] in (None, "") for key in keys)


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return repr(value)
