from __future__ import annotations

import datetime as dt
import re
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

from .models import Paper, SearchPlan
from .utils import compact_text, encode_query, rate_limit_pause, request_json, request_text, safe_fetch


def search_all(plan: SearchPlan, per_query_limit: int = 10) -> list[Paper]:
    papers: list[Paper] = []
    tools = [search_arxiv, search_semantic_scholar, search_openalex, search_crossref, search_openreview]
    futures = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        for query in plan.search_queries:
            for tool in tools:
                futures.append(executor.submit(tool, query, per_query_limit, plan.since_year))
        for future in as_completed(futures):
            papers.extend(safe_fetch(future.result, []))
    return papers


def search_arxiv(query: str, limit: int, since_year: int | None) -> list[Paper]:
    search_query = f'all:"{query}"'
    if since_year:
        search_query += f" AND submittedDate:[{since_year}01010000 TO 999912312359]"
    url = "https://export.arxiv.org/api/query?" + encode_query(
        {
            "search_query": search_query,
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    text = safe_fetch(lambda: request_text(url, timeout=12), "")
    if not text:
        return []
    root = ET.fromstring(text)
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ns):
        title = compact_text(_xml_text(entry, "atom:title", ns))
        summary = compact_text(_xml_text(entry, "atom:summary", ns))
        published = _xml_text(entry, "atom:published", ns)
        year = int(published[:4]) if published[:4].isdigit() else None
        arxiv_url = _xml_text(entry, "atom:id", ns)
        arxiv_id = arxiv_url.rsplit("/", 1)[-1] if arxiv_url else None
        authors = [compact_text(a.findtext("atom:name", default="", namespaces=ns)) for a in entry.findall("atom:author", ns)]
        pdf_url = None
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href")
        papers.append(
            Paper(
                title=title,
                authors=[a for a in authors if a],
                year=year,
                venue="arXiv",
                abstract=summary,
                arxiv_id=arxiv_id,
                url=arxiv_url,
                pdf_url=pdf_url,
                source="arxiv",
                sources=["arxiv"],
                raw={"query": query},
            )
        )
    return papers


def search_semantic_scholar(query: str, limit: int, since_year: int | None) -> list[Paper]:
    fields = "title,authors,year,abstract,venue,citationCount,externalIds,url,openAccessPdf"
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + encode_query(
        {"query": query, "limit": limit, "fields": fields, "year": f"{since_year}-" if since_year else None}
    )
    data = safe_fetch(lambda: request_json(url, timeout=12), {})
    papers: list[Paper] = []
    for item in data.get("data", []) if isinstance(data, dict) else []:
        external = item.get("externalIds") or {}
        open_pdf = item.get("openAccessPdf") or {}
        papers.append(
            Paper(
                title=compact_text(item.get("title")),
                authors=[a.get("name", "") for a in item.get("authors", []) if a.get("name")],
                year=item.get("year"),
                venue=item.get("venue"),
                abstract=compact_text(item.get("abstract")),
                doi=external.get("DOI"),
                arxiv_id=external.get("ArXiv"),
                url=item.get("url"),
                pdf_url=open_pdf.get("url"),
                citation_count=item.get("citationCount"),
                source="semantic_scholar",
                sources=["semantic_scholar"],
                raw={"query": query, "paperId": item.get("paperId")},
            )
        )
    return [p for p in papers if p.title]


def search_openalex(query: str, limit: int, since_year: int | None) -> list[Paper]:
    filters = []
    if since_year:
        filters.append(f"from_publication_date:{since_year}-01-01")
    url = "https://api.openalex.org/works?" + encode_query(
        {"search": query, "per-page": limit, "filter": ",".join(filters) if filters else None}
    )
    data = safe_fetch(lambda: request_json(url, timeout=12), {})
    papers: list[Paper] = []
    for item in data.get("results", []) if isinstance(data, dict) else []:
        authors = []
        for auth in item.get("authorships", []):
            name = (auth.get("author") or {}).get("display_name")
            if name:
                authors.append(name)
        doi = item.get("doi")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi.removeprefix("https://doi.org/")
        pdf_url = ((item.get("best_oa_location") or {}).get("pdf_url") or None)
        papers.append(
            Paper(
                title=compact_text(item.get("display_name")),
                authors=authors,
                year=item.get("publication_year"),
                venue=((item.get("primary_location") or {}).get("source") or {}).get("display_name"),
                abstract=_openalex_abstract(item.get("abstract_inverted_index")),
                doi=doi,
                url=item.get("id"),
                pdf_url=pdf_url,
                citation_count=item.get("cited_by_count"),
                source="openalex",
                sources=["openalex"],
                raw={"query": query},
            )
        )
    return [p for p in papers if p.title]


def search_crossref(query: str, limit: int, since_year: int | None) -> list[Paper]:
    filters = f"from-pub-date:{since_year}" if since_year else None
    url = "https://api.crossref.org/works?" + encode_query({"query": query, "rows": limit, "filter": filters})
    data = safe_fetch(lambda: request_json(url, timeout=12), {})
    items = ((data.get("message") or {}).get("items") or []) if isinstance(data, dict) else []
    papers: list[Paper] = []
    for item in items:
        title = compact_text((item.get("title") or [""])[0])
        authors = []
        for a in item.get("author", []):
            name = " ".join(x for x in [a.get("given"), a.get("family")] if x)
            if name:
                authors.append(name)
        year = _crossref_year(item)
        papers.append(
            Paper(
                title=title,
                authors=authors,
                year=year,
                venue=(item.get("container-title") or [None])[0],
                abstract=compact_text(re.sub("<[^>]+>", " ", item.get("abstract") or "")) or None,
                doi=item.get("DOI"),
                url=item.get("URL"),
                citation_count=item.get("is-referenced-by-count"),
                source="crossref",
                sources=["crossref"],
                raw={"query": query},
            )
        )
    return [p for p in papers if p.title]


def search_openreview(query: str, limit: int, since_year: int | None) -> list[Paper]:
    url = "https://api2.openreview.net/notes/search?" + encode_query({"term": query, "limit": limit})
    data = safe_fetch(lambda: request_json(url, timeout=12), {})
    notes = data.get("notes", []) if isinstance(data, dict) else []
    papers: list[Paper] = []
    for note in notes:
        content = note.get("content") or {}
        title = _content_value(content.get("title"))
        abstract = _content_value(content.get("abstract"))
        authors = _content_value(content.get("authors")) or []
        if isinstance(authors, str):
            authors = [authors]
        cdate = note.get("cdate")
        year = dt.datetime.fromtimestamp(cdate / 1000).year if cdate else None
        if since_year and year and year < since_year:
            continue
        paper_id = note.get("id")
        pdf_url = f"https://openreview.net/pdf?id={paper_id}" if paper_id else None
        papers.append(
            Paper(
                title=compact_text(title),
                authors=authors,
                year=year,
                venue=note.get("forum"),
                abstract=compact_text(abstract),
                openreview_id=paper_id,
                url=f"https://openreview.net/forum?id={paper_id}" if paper_id else None,
                pdf_url=pdf_url,
                source="openreview",
                sources=["openreview"],
                raw={"query": query},
            )
        )
    return [p for p in papers if p.title]


def _xml_text(entry: ET.Element, path: str, ns: dict[str, str]) -> str:
    value = entry.findtext(path, default="", namespaces=ns)
    return value or ""


def _openalex_abstract(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        for pos in positions:
            words.append((pos, word))
    return " ".join(word for _, word in sorted(words))


def _crossref_year(item: dict) -> int | None:
    for key in ("published-print", "published-online", "issued"):
        parts = ((item.get(key) or {}).get("date-parts") or [[]])[0]
        if parts and isinstance(parts[0], int):
            return parts[0]
    return None


def _content_value(value):
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def iter_search_errors(_: Iterable[Paper]) -> list[str]:
    return []
