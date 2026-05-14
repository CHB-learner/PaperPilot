from __future__ import annotations

import json
import re
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
    text = _paper_text(paper)
    query_terms = _query_terms(plan)
    core_hits = sorted(term for term in CORE_TERMS | set(query_terms) if term and term in text)
    adjacent_hits = sorted(term for term in ADJACENT_TERMS if term in text)
    negative_hits = sorted(term for term in protocol.negative_keywords if term.lower() in text)

    score = 0.0
    score += min(0.7, 0.18 * len(core_hits))
    score += min(0.2, 0.06 * len(adjacent_hits))
    if "rna" in text:
        score += 0.1
    if paper.has_code:
        score += 0.05
    if paper.abstract:
        score += 0.05
    score -= min(0.7, 0.18 * len(negative_hits))
    score = max(0.0, min(1.0, score))

    title = normalize_title(paper.title)
    if any(marker in title for marker in ["autodock vina", "rna seqc", "rtm align", "prolif", "sharing biological data"]):
        label = "exclude"
        reason = "Title matches a known adjacent or off-topic tool category for this task."
    elif negative_hits and len(core_hits) < 2:
        label = "exclude"
        reason = "Negative topic signals dominate and task-specific evidence is weak."
    elif score >= 0.55 and core_hits:
        label = "core"
        reason = "The paper directly matches task-specific design or inverse-folding terminology."
    elif score >= 0.32 and (core_hits or adjacent_hits):
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
    return " ".join([paper.title, paper.abstract or "", paper.venue or ""]).lower()


def _query_terms(plan: SearchPlan) -> list[str]:
    terms = set()
    for value in [plan.recommended_query, *plan.search_queries, *plan.subtopics]:
        lowered = value.lower()
        for phrase in re.findall(r"[a-z][a-z0-9 -]{3,}", lowered):
            phrase = re.sub(r"\s+", " ", phrase).strip()
            if len(phrase.split()) >= 2:
                terms.add(phrase)
    return sorted(terms)


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
