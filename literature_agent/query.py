from __future__ import annotations

from dataclasses import dataclass

from .openai_client import OpenAIClient
from .prompts import run_prompt_json


AMBIGUOUS_TERMS = {"rna", "dna", "protein", "agent", "transformer", "diffusion", "alignment", "retrieval"}


@dataclass
class QueryUnderstanding:
    original_keyword: str
    recommended_query: str
    possible_interpretations: list[str]
    included_scope: list[str]
    excluded_scope: list[str]
    search_terms: list[str]
    needs_confirmation: bool
    rationale: str

    def to_markdown(self) -> str:
        lines = [
            "# Query Understanding",
            "",
            f"- Original keyword: `{self.original_keyword}`",
            f"- Recommended query: `{self.recommended_query}`",
            f"- Needs confirmation: `{self.needs_confirmation}`",
            "",
            "## Possible Interpretations",
            *[f"- {item}" for item in self.possible_interpretations],
            "",
            "## Included Scope",
            *[f"- {item}" for item in self.included_scope],
            "",
            "## Excluded Scope",
            *[f"- {item}" for item in self.excluded_scope],
            "",
            "## Search Terms",
            *[f"- {item}" for item in self.search_terms],
            "",
            "## Rationale",
            self.rationale,
            "",
        ]
        return "\n".join(lines)


def understand_query(keyword: str, client: OpenAIClient | None) -> QueryUnderstanding:
    fallback = heuristic_understanding(keyword)
    if not client or not client.available:
        return fallback
    payload = run_prompt_json(
        client,
        "query_understanding",
        fallback={
            "original_keyword": fallback.original_keyword,
            "recommended_query": fallback.recommended_query,
            "possible_interpretations": fallback.possible_interpretations,
            "included_scope": fallback.included_scope,
            "excluded_scope": fallback.excluded_scope,
            "search_terms": fallback.search_terms,
            "needs_confirmation": fallback.needs_confirmation,
            "rationale": fallback.rationale,
        },
        keyword=repr(keyword),
    )
    recommended_query = str(payload.get("recommended_query") or fallback.recommended_query)
    included_scope = _as_list(payload.get("included_scope"), fallback.included_scope)
    excluded_scope = _as_list(payload.get("excluded_scope"), fallback.excluded_scope)
    rationale = str(payload.get("rationale") or fallback.rationale)
    if _looks_like_unrequested_ai_narrowing(keyword, recommended_query, included_scope, excluded_scope):
        recommended_query = fallback.recommended_query
        included_scope = fallback.included_scope
        excluded_scope = fallback.excluded_scope
        rationale = (
            rationale
            + " PaperPilot kept the broader user scope because the request did not explicitly ask for AI-only papers."
        )
    return QueryUnderstanding(
        original_keyword=str(payload.get("original_keyword") or keyword),
        recommended_query=recommended_query,
        possible_interpretations=_as_list(payload.get("possible_interpretations"), fallback.possible_interpretations),
        included_scope=included_scope,
        excluded_scope=excluded_scope,
        search_terms=_as_list(payload.get("search_terms"), fallback.search_terms),
        needs_confirmation=bool(payload.get("needs_confirmation", fallback.needs_confirmation)),
        rationale=rationale,
    )


def _as_list(value, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return fallback


def heuristic_understanding(keyword: str) -> QueryUnderstanding:
    lowered = keyword.strip().lower()
    ambiguous = lowered in AMBIGUOUS_TERMS or len(lowered.split()) <= 1
    if lowered == "rna":
        interpretations = [
            "RNA biology and molecular mechanisms",
            "RNA structure prediction with machine learning",
            "RNA design and sequence generation",
            "RNA foundation models / RNA language models",
            "AI for genomics and transcriptomics",
        ]
        terms = [
            "RNA language model",
            "RNA foundation model",
            "RNA structure prediction deep learning",
            "RNA design generative model",
            "AI for RNA genomics",
        ]
        recommended = "RNA foundation model OR RNA structure prediction OR RNA design deep learning"
    else:
        interpretations = [keyword, f"methods and protocols for {keyword}", f"recent reviews about {keyword}"]
        terms = [keyword, f"{keyword} methods", f"{keyword} review", f"{keyword} benchmark"]
        recommended = keyword
    return QueryUnderstanding(
        original_keyword=keyword,
        recommended_query=recommended,
        possible_interpretations=interpretations,
        included_scope=["User-requested research scope", "recent papers and reviews", "papers with metadata, PDF links, or code links"],
        excluded_scope=["Non-scholarly webpages", "paywalled PDF bypassing", "unverified claims"],
        search_terms=terms,
        needs_confirmation=ambiguous,
        rationale="Heuristic fallback used because no LLM result was available." if ambiguous else "Keyword is specific enough for direct search.",
    )


def _looks_like_unrequested_ai_narrowing(
    original_keyword: str,
    recommended_query: str,
    included_scope: list[str],
    excluded_scope: list[str],
) -> bool:
    original = original_keyword.lower()
    recommended = " ".join([recommended_query, *included_scope, *excluded_scope]).lower()
    ai_terms = {
        "ai",
        "artificial intelligence",
        "machine learning",
        "deep learning",
        "neural network",
        "foundation model",
        "large language model",
        "computational model",
    }
    user_requested_ai = any(term in original for term in ai_terms)
    llm_added_ai_gate = any(term in recommended for term in ai_terms) and any(
        marker in recommended for marker in ["without any ai", "without ai", "ai-only", "solely", "purely wet-lab"]
    )
    return not user_requested_ai and llm_added_ai_gate
