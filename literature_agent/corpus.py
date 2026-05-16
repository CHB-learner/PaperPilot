from __future__ import annotations

import json
import re
import datetime as dt
from collections import Counter
from difflib import SequenceMatcher

from .models import CodeArtifact, CorpusItem, InclusionDecision, Paper, ResearchProtocol, SearchPlan
from .openai_client import OpenAIClient
from .processing import deduplicate, resolve_code_links
from .prompts import run_prompt_json
from .utils import normalize_title, stable_id


CORE_TERMS = {
    "inverse folding",
    "inverse design",
    "rna design",
    "sequence design",
    "computational rna design",
    "structure design",
    "designability",
    "eterna100",
    "grnade",
    "ribodiffusion",
    "rider",
    "arnaque",
    "greed-rna",
    "samfeo",
    "rna-undesign",
    "rwkv-if",
    "rna-efm",
    "mxfold",
}

ADJACENT_TERMS = {
    "secondary structure prediction",
    "structure prediction",
    "folding engine",
    "thermodynamic",
    "sequence-structure",
    "foundation model",
    "language model",
    "aptamer",
}


def build_corpus(
    raw_papers: list[Paper],
    plan: SearchPlan,
    protocol: ResearchProtocol,
    client: OpenAIClient | None,
) -> tuple[list[CorpusItem], dict]:
    resolved = resolve_code_links(raw_papers)
    deduped, dedup_stats = enhanced_deduplicate(resolved)
    items = [
        CorpusItem(
            citation_key=citation_key(paper, idx),
            paper=paper,
            inclusion=classify_paper(paper, plan, protocol),
            code_artifacts=code_artifacts_for_paper(paper),
        )
        for idx, paper in enumerate(deduped, start=1)
    ]
    items = maybe_llm_screen(items, plan, protocol, client)
    items.sort(key=lambda item: (label_rank(item.inclusion.label), -item.paper.rank_score, -(item.paper.year or 0), item.paper.title))
    return items, dedup_stats


def corpus_items_from_papers(
    papers: list[Paper],
    plan: SearchPlan,
    protocol: ResearchProtocol,
    client: OpenAIClient | None,
) -> list[CorpusItem]:
    items = [
        CorpusItem(
            citation_key=citation_key(paper, idx),
            paper=paper,
            inclusion=classify_paper(paper, plan, protocol),
            code_artifacts=code_artifacts_for_paper(paper),
        )
        for idx, paper in enumerate(papers, start=1)
    ]
    items = maybe_llm_screen(items, plan, protocol, client)
    items.sort(key=lambda item: (label_rank(item.inclusion.label), -item.paper.rank_score, -(item.paper.year or 0), item.paper.title))
    return items


def enhanced_deduplicate(papers: list[Paper]) -> tuple[list[Paper], dict]:
    first = deduplicate(papers)
    merged: list[Paper] = []
    duplicate_groups = 0
    for paper in first:
        match = _find_title_match(merged, paper)
        if not match:
            paper.sources = sorted(set(paper.sources or [paper.source]))
            merged.append(paper)
            continue
        duplicate_groups += 1
        _merge_paper(match, paper)
    return merged, {
        "raw_count": len(papers),
        "after_identifier_dedup": len(first),
        "after_title_similarity_dedup": len(merged),
        "title_similarity_merges": duplicate_groups,
    }


def _find_title_match(existing: list[Paper], paper: Paper) -> Paper | None:
    norm = normalize_title(paper.title)
    for candidate in existing:
        candidate_norm = normalize_title(candidate.title)
        if not norm or not candidate_norm:
            continue
        if norm == candidate_norm:
            return candidate
        ratio = SequenceMatcher(None, norm, candidate_norm).ratio()
        years_close = not paper.year or not candidate.year or abs(paper.year - candidate.year) <= 1
        author_overlap = bool(set(_author_last_names(paper)) & set(_author_last_names(candidate)))
        if ratio >= 0.93 and (years_close or author_overlap):
            return candidate
    return None


def _merge_paper(current: Paper, paper: Paper) -> None:
    current.sources = sorted(set(current.sources + paper.sources + [paper.source]))
    for field in ("abstract", "doi", "arxiv_id", "openreview_id", "url", "pdf_url", "venue", "github_url", "code_url", "code_source"):
        if not getattr(current, field) and getattr(paper, field):
            setattr(current, field, getattr(paper, field))
    current.has_code = current.has_code or paper.has_code
    if paper.citation_count and (not current.citation_count or paper.citation_count > current.citation_count):
        current.citation_count = paper.citation_count
    if paper.year and (not current.year or paper.year > current.year):
        current.year = paper.year
    if len(paper.authors) > len(current.authors):
        current.authors = paper.authors
    current.raw.setdefault("identifiers", {}).update((paper.raw or {}).get("identifiers") or {})


def classify_paper(paper: Paper, plan: SearchPlan, protocol: ResearchProtocol) -> InclusionDecision:
    paper_year = _coerce_year_for_screening(paper.year, plan.since_year)
    if paper_year != paper.year:
        paper.year = paper_year
    text = _paper_text(paper)
    phrase_terms = set(_query_terms(plan))
    primary_tokens = _topic_tokens([plan.recommended_query])
    topic_tokens = _topic_tokens([plan.recommended_query, *plan.search_queries, *plan.subtopics])
    non_ascii_plan_tokens = _topic_tokens_non_ascii([plan.recommended_query, *plan.search_queries, *plan.subtopics, *phrase_terms])
    if _is_rna_task(plan):
        static_core_terms = CORE_TERMS
        static_adjacent_terms = ADJACENT_TERMS
    else:
        static_core_terms = set(_query_terms(plan)) | {term for term in topic_tokens if len(term) >= 3}
        static_adjacent_terms = set(_topic_tokens(plan.search_queries[:4]))
    phrase_hits = sorted(term for term in static_core_terms | phrase_terms if term and term in text)
    primary_hits = sorted(token for token in primary_tokens if token in text)
    token_hits = sorted(token for token in topic_tokens if token in text)
    core_hits = sorted(set(phrase_hits + primary_hits + token_hits))
    adjacent_hits = sorted(term for term in static_adjacent_terms if term in text)
    negative_hits = sorted(term for term in protocol.negative_keywords if term.lower() in text)

    score = 0.0
    score += min(0.55, 0.25 * len(phrase_hits))
    score += min(0.3, 0.12 * len(primary_hits))
    score += min(0.25, 0.08 * len(token_hits))
    score += min(0.2, 0.06 * len(adjacent_hits))
    if paper.has_code:
        score += 0.05
    if paper.abstract:
        score += 0.05
    if non_ascii_plan_tokens and not _contains_ascii(non_ascii_plan_tokens):
        score += 0.06
    score -= min(0.5 if _is_rna_task(plan) else 0.35, 0.18 * len(negative_hits))
    score = max(0.0, min(1.0, score))

    if plan.since_year and paper_year and paper_year < plan.since_year:
        return InclusionDecision(
            label="exclude",
            score=0.0,
            reason="Publication year is below requested since-year threshold.",
            matched_terms=core_hits + adjacent_hits,
            negative_hits=negative_hits,
        )

    title = normalize_title(paper.title)
    off_topic_markers = ["autodock vina", "prolif"]
    if _is_rna_task(plan):
        off_topic_markers.extend(["rna seqc", "rtm align", "sharing biological data"])
    if any(marker in title for marker in off_topic_markers):
        label = "exclude"
        reason = "Title matches a known adjacent or off-topic tool category for this task."
    elif negative_hits and not phrase_hits and len(primary_hits) < 2:
        label = "exclude"
        reason = "Negative topic signals dominate and task-specific evidence is weak."
    elif score >= (0.5 if _is_rna_task(plan) else 0.3) and (phrase_hits or primary_hits or len(token_hits) >= 2):
        label = "core"
        reason = "The paper directly matches the requested topic terminology."
    elif score >= (0.2 if _is_rna_task(plan) else 0.12) and (primary_hits or token_hits or adjacent_hits):
        label = "adjacent"
        reason = "The paper is related but not central enough for the core synthesis."
    else:
        label = "exclude"
        reason = "Insufficient task-specific evidence in title and abstract."

    return InclusionDecision(
        label=label,
        score=round(score, 4),
        reason=reason,
        matched_terms=core_hits + adjacent_hits,
        negative_hits=negative_hits,
    )


def maybe_llm_screen(
    items: list[CorpusItem],
    plan: SearchPlan,
    protocol: ResearchProtocol,
    client: OpenAIClient | None,
) -> list[CorpusItem]:
    if not client or not client.available:
        return items
    uncertain = [item for item in items if 0.25 <= item.inclusion.score <= 0.65][:30]
    if not uncertain:
        return items
    payload = {
        "research_question": protocol.research_question,
        "recommended_query": plan.recommended_query,
        "items": [
            {
                "citation_key": item.citation_key,
                "title": item.paper.title,
                "abstract": (item.paper.abstract or "")[:900],
                "current_label": item.inclusion.label,
                "current_reason": item.inclusion.reason,
            }
            for item in uncertain
        ],
    }
    result = run_prompt_json(
        client,
        "screening",
        fallback={"decisions": []},
        payload=json.dumps(payload, ensure_ascii=False),
    )
    decisions = {str(item.get("citation_key")): item for item in result.get("decisions", []) if isinstance(item, dict)}
    for item in items:
        decision = decisions.get(item.citation_key)
        if not decision:
            continue
        label = str(decision.get("label") or item.inclusion.label).lower()
        if label not in {"core", "adjacent", "exclude"}:
            continue
        item.inclusion.label = label
        try:
            item.inclusion.score = float(decision.get("score", item.inclusion.score))
        except (TypeError, ValueError):
            pass
        item.inclusion.reason = str(decision.get("reason") or item.inclusion.reason)
    return items


def code_artifacts_for_paper(paper: Paper) -> list[CodeArtifact]:
    artifacts: list[CodeArtifact] = []
    for url in [paper.github_url, paper.code_url]:
        if not url or any(existing.url == url for existing in artifacts):
            continue
        kind = "github" if "github.com" in url.lower() else "gitlab" if "gitlab.com" in url.lower() else "huggingface" if "huggingface.co" in url.lower() else "project"
        confidence, reason = code_confidence(paper, url)
        artifacts.append(CodeArtifact(url=url, kind=kind, source=paper.code_source or "metadata", confidence=confidence, confidence_reason=reason))
    return artifacts


def code_confidence(paper: Paper, url: str) -> tuple[float, str]:
    title_tokens = _important_tokens(paper.title)
    url_text = url.lower()
    matches = [token for token in title_tokens if token in url_text]
    if "github.com" not in url_text and "gitlab.com" not in url_text and "huggingface.co" not in url_text:
        return 0.45, "Project URL found, but repository host is not explicit."
    if len(matches) >= max(1, min(3, len(title_tokens) // 2)):
        return 0.85, "Repository URL matches distinctive title tokens."
    if any(author.split()[-1].lower() in url_text for author in paper.authors[:4] if author.split()):
        return 0.7, "Repository URL matches an author name."
    if paper.code_source == "github_search":
        return 0.6, "Repository was found by title-based GitHub search."
    return 0.55, "Repository URL is present in metadata but has weak title-token evidence."


def citation_key(paper: Paper, index: int) -> str:
    author = "paper"
    if paper.authors:
        parts = re.findall(r"[A-Za-z]+", paper.authors[0].split()[-1].lower())
        if parts:
            author = parts[0]
    year = str(paper.year or "nd")
    title_token = next(iter(_important_tokens(paper.title)), "work")
    return f"{author}{year}{title_token}{stable_id(paper.title)[:4]}{index}"


def label_rank(label: str) -> int:
    return {"core": 0, "adjacent": 1, "exclude": 2}.get(label, 3)


def split_corpus(items: list[CorpusItem]) -> tuple[list[CorpusItem], list[CorpusItem], list[CorpusItem]]:
    core = [item for item in items if item.inclusion.label == "core"]
    adjacent = [item for item in items if item.inclusion.label == "adjacent"]
    excluded = [item for item in items if item.inclusion.label == "exclude"]
    return core, adjacent, excluded


def _paper_text(paper: Paper) -> str:
    return " ".join(
        [
            paper.title or "",
            paper.abstract or "",
            str(paper.venue or ""),
        ]
    ).lower()


def _query_terms(plan: SearchPlan) -> list[str]:
    terms = set()
    for value in [plan.recommended_query, *plan.search_queries, *plan.subtopics]:
        lowered = value.lower()
        for phrase in re.findall(r"[a-z][a-z0-9 -]{2,}", lowered):
            phrase = re.sub(r"\s+", " ", phrase).strip()
            if len(phrase.split()) >= 2:
                terms.add(phrase)
        for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
            terms.add(phrase.strip())
    return sorted(terms)


def _is_rna_task(plan: SearchPlan) -> bool:
    task_text = " ".join([plan.recommended_query, *plan.search_queries, *plan.subtopics]).lower()
    return bool(re.search(r"\brna\b|ribonucleic", task_text))


def _topic_tokens(values: list[str]) -> list[str]:
    stop = {
        "about",
        "across",
        "analysis",
        "application",
        "applications",
        "approach",
        "approaches",
        "and",
        "based",
        "benchmark",
        "benchmarks",
        "classic",
        "code",
        "data",
        "dataset",
        "datasets",
        "development",
        "different",
        "english",
        "evaluation",
        "for",
        "framework",
        "general",
        "method",
        "methods",
        "model",
        "models",
        "paper",
        "papers",
        "protocol",
        "protocols",
        "recent",
        "research",
        "review",
        "reviews",
        "study",
        "studies",
        "survey",
        "surveys",
        "system",
        "systems",
        "task",
        "tasks",
        "technique",
        "techniques",
        "using",
        "with",
        "without",
    }
    tokens: list[str] = []
    for value in values:
        tokens.extend(_topic_tokens_non_ascii(value))
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", value.lower()):
            token = token.strip("-")
            if len(token) < 3 or token in stop:
                continue
            tokens.append(token)
    return list(dict.fromkeys(tokens))[:24]


def _coerce_year_for_screening(year: int | str | None, since_year: int | None) -> int | None:
    if year is None:
        return None
    if isinstance(year, bool):
        return None
    if isinstance(year, int):
        if year < 1500 or year > dt.date.today().year + 1:
            return None
        if since_year is not None and year < max(1500, since_year - 2):
            return None
        return year
    value = str(year).strip()
    if not value:
        return None
    match = re.search(r"(19|20)\d{2}", value)
    if not match:
        return None
    parsed = int(match.group(0))
    if parsed < 1500 or parsed > dt.date.today().year + 1:
        return None
    if since_year is not None and parsed < max(1500, since_year - 2):
        return None
    return parsed


def _topic_tokens_non_ascii(values: list[str]) -> list[str]:
    tokens: list[str] = []
    for value in values:
        lowered = value.lower()
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
            # Keep concise CJK chunks and remove very generic fragments.
            if len(chunk) < 2 or chunk in {"相关", "研究", "方法"}:
                continue
            tokens.append(chunk)
    return list(dict.fromkeys(tokens))


def _contains_ascii(tokens: list[str]) -> bool:
    return any(any("a" <= char <= "z" for char in token.lower()) for token in tokens)


def _important_tokens(title: str) -> list[str]:
    stop = {
        "with",
        "from",
        "into",
        "using",
        "based",
        "learning",
        "model",
        "models",
        "method",
        "methods",
        "design",
        "sequence",
        "sequences",
        "rna",
        "deep",
        "structure",
        "structures",
        "prediction",
        "analysis",
        "the",
        "and",
        "for",
        "via",
    }
    tokens = [token for token in re.findall(r"[a-zA-Z0-9]+", title.lower()) if len(token) >= 4 and token not in stop]
    counts = Counter(tokens)
    return [token for token, _ in counts.most_common(10)]


def _author_last_names(paper: Paper) -> list[str]:
    return [author.split()[-1].lower() for author in paper.authors if author.split()]
