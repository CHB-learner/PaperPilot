from __future__ import annotations

import math
import datetime as dt
import re
import urllib.parse
from collections import Counter

from .models import Paper
from .utils import normalize_title, rate_limit_pause, request_json, safe_fetch


CODE_RE = re.compile(r"https?://(?:www\.)?(github\.com|gitlab\.com|huggingface\.co)/[^\s)\]}>\"']+", re.I)
PROJECT_RE = re.compile(r"https?://[^\s)\]}>\"']*(?:project|code|demo|github)[^\s)\]}>\"']*", re.I)


def deduplicate(papers: list[Paper]) -> list[Paper]:
    merged: dict[str, Paper] = {}
    key_index: dict[str, str] = {}
    for paper in papers:
        keys = dedup_keys(paper)
        match_key = next((key_index[key] for key in keys if key in key_index), None)
        if not match_key:
            key = keys[0]
            paper.sources = sorted(set(paper.sources or [paper.source]))
            merged[key] = paper
            for alias in keys:
                key_index[alias] = key
            continue
        current = merged[match_key]
        current.sources = sorted(set(current.sources + paper.sources + [paper.source]))
        for field in ("abstract", "doi", "arxiv_id", "openreview_id", "url", "pdf_url", "venue"):
            if not getattr(current, field) and getattr(paper, field):
                setattr(current, field, getattr(paper, field))
        current.raw.setdefault("identifiers", {}).update((paper.raw or {}).get("identifiers") or {})
        if paper.citation_count and (not current.citation_count or paper.citation_count > current.citation_count):
            current.citation_count = paper.citation_count
        if paper.year and (not current.year or paper.year > current.year):
            current.year = paper.year
        if len(paper.authors) > len(current.authors):
            current.authors = paper.authors
        for alias in keys:
            key_index[alias] = match_key
    return list(merged.values())


def dedup_key(paper: Paper) -> str:
    return dedup_keys(paper)[0]


def dedup_keys(paper: Paper) -> list[str]:
    keys: list[str] = []
    if paper.doi:
        keys.append("doi:" + paper.doi.lower())
    if paper.arxiv_id:
        keys.append("arxiv:" + paper.arxiv_id.lower())
    identifiers = (paper.raw or {}).get("identifiers") or {}
    for key in ["pmid", "pmcid", "dblp_key"]:
        if identifiers.get(key):
            keys.append(f"{key}:{str(identifiers[key]).lower()}")
    if paper.openreview_id:
        keys.append("openreview:" + paper.openreview_id)
    keys.append("title:" + normalize_title(paper.title))
    return list(dict.fromkeys(keys))


def resolve_code_links(papers: list[Paper]) -> list[Paper]:
    for paper in papers:
        haystack = "\n".join([paper.title, paper.abstract or "", paper.url or "", paper.pdf_url or ""])
        matches = CODE_RE.findall(haystack)
        full_matches = re.findall(CODE_RE, haystack)
        urls = re.findall(r"https?://(?:www\.)?(?:github\.com|gitlab\.com|huggingface\.co)/[^\s)\]}>\"']+", haystack, re.I)
        if urls:
            paper.has_code = True
            paper.code_url = urls[0].rstrip(".,;")
            paper.code_source = "metadata"
            if "github.com" in paper.code_url.lower():
                paper.github_url = paper.code_url
        else:
            project = PROJECT_RE.search(haystack)
            if project and _looks_like_code_project_url(project.group(0)):
                paper.has_code = True
                paper.code_url = project.group(0).rstrip(".,;")
                paper.code_source = "metadata"
    return papers


def enrich_github_links(papers: list[Paper], max_checks: int = 25) -> dict:
    checked = 0
    enriched = 0
    skipped = 0
    for paper in papers:
        if checked >= max_checks:
            break
        if paper.github_url or not paper.title:
            skipped += 1
            continue
        checked += 1
        repo_url = search_github_for_paper(paper)
        if repo_url:
            paper.has_code = True
            paper.github_url = repo_url
            paper.code_url = repo_url
            paper.code_source = "github_search"
            enriched += 1
        rate_limit_pause(0.35)
    return {"checked": checked, "enriched": enriched, "skipped_existing_code": skipped}


def search_github_for_paper(paper: Paper) -> str | None:
    clean_title = re.sub(r"<[^>]+>", " ", paper.title)
    title_tokens = _title_tokens(clean_title)
    if not title_tokens:
        return None
    query = f"{clean_title} in:name,description,readme"
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": query, "sort": "stars", "order": "desc", "per_page": 5}
    )
    data = safe_fetch(lambda: request_json(url, timeout=12), {})
    for item in data.get("items", []) if isinstance(data, dict) else []:
        candidate_text = " ".join(
            [
                item.get("full_name") or "",
                item.get("name") or "",
                item.get("description") or "",
                item.get("html_url") or "",
            ]
        )
        if _github_match_score(title_tokens, candidate_text) >= _github_match_threshold(title_tokens):
            return item.get("html_url")
    return None


def apply_github_filter(papers: list[Paper], mode: str) -> list[Paper]:
    if mode == "required":
        return [p for p in papers if p.github_url or p.has_code]
    if mode == "none":
        return [p for p in papers if not (p.github_url or p.has_code)]
    return papers


def rank_papers(papers: list[Paper], keyword: str, since_year: int | None) -> list[Paper]:
    query_terms = _terms(keyword)
    current_year = dt.date.today().year
    for paper in papers:
        paper_year = _coerce_year_for_ranking(paper.year)
        if paper_year != paper.year:
            paper.year = paper_year
        text = " ".join([_as_text(paper.title), _as_text(paper.abstract), _as_text(paper.venue)]).lower()
        term_hits = sum(1 for term in query_terms if term in text)
        relevance = term_hits / max(1, len(query_terms))
        recency = 0.0
        if paper_year:
            recency = max(0.0, 1.0 - min(10, current_year - paper_year) / 10)
        citations = math.log1p(paper.citation_count or 0) / 10
        venue_bonus = 0.15 if paper.venue and any(v in paper.venue.lower() for v in ["neurips", "iclr", "icml", "acl", "cvpr", "emnlp", "openreview", "arxiv"]) else 0
        pdf_bonus = 0.1 if paper.pdf_url else 0
        code_bonus = 0.15 if paper.has_code else 0
        source_diversity_bonus = min(0.12, 0.03 * max(0, len(set(paper.sources or [paper.source])) - 1))
        paper.relevance_score = round(relevance, 4)
        paper.rank_score = round(relevance * 2 + recency + citations + venue_bonus + pdf_bonus + code_bonus + source_diversity_bonus, 4)
    return sorted(papers, key=lambda p: p.rank_score, reverse=True)


def _terms(keyword: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", keyword.lower())
    counts = Counter(t for t in tokens if len(t) > 1)
    return list(counts) or [keyword.lower()]


def _title_tokens(title: str) -> set[str]:
    stopwords = {
        "with",
        "from",
        "into",
        "using",
        "based",
        "towards",
        "toward",
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
        "for",
        "and",
        "the",
        "via",
    }
    return {token for token in re.findall(r"[a-zA-Z0-9]+", title.lower()) if len(token) >= 4 and token not in stopwords}


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return " ".join(_as_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("display_name", "name", "title", "value", "text"):
            if value.get(key):
                return _as_text(value.get(key))
        return " ".join(_as_text(item) for item in value.values())
    return str(value)


def _coerce_year_for_ranking(year) -> int | None:
    if isinstance(year, bool):
        return None
    if isinstance(year, int):
        if year < 1500:
            return None
        current_year = dt.date.today().year
        if year > current_year + 1:
            return None
        return year
    if year is None:
        return None
    text = str(year).strip()
    if not text:
        return None
    match = re.search(r"(19|20)\d{2}", text)
    if not match:
        return None
    parsed = int(match.group(0))
    current_year = dt.date.today().year
    if parsed > current_year + 1 or parsed < 1500:
        return None
    return parsed


def _github_match_score(title_tokens: set[str], candidate_text: str) -> int:
    candidate = candidate_text.lower()
    return sum(1 for token in title_tokens if token in candidate)


def _github_match_threshold(title_tokens: set[str]) -> int:
    if len(title_tokens) <= 2:
        return len(title_tokens)
    return max(2, min(4, len(title_tokens) // 2))


def _looks_like_code_project_url(url: str) -> bool:
    lowered = url.lower().rstrip(".,;")
    if lowered.endswith(".pdf"):
        return False
    if "projecteuclid.org" in lowered:
        return False
    return any(marker in lowered for marker in ["/code", "/codes", "/demo", "/project", "paperswithcode.com"])
