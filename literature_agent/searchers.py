from __future__ import annotations

import datetime as dt
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

from .models import Paper, SearchPlan
from .sources import SOURCE_SPECS, SourceConfig, configured_api_key, resolve_enabled_sources
from .utils import compact_text, encode_query, post_json, rate_limit_pause, request_json, request_text, safe_fetch


def search_all(
    plan: SearchPlan,
    per_query_limit: int = 10,
    *,
    source_mode: str = "auto",
    source_configs: dict[str, SourceConfig] | None = None,
    enable_sources: list[str] | None = None,
    disable_sources: list[str] | None = None,
) -> list[Paper]:
    papers, _ = search_all_with_diagnostics(
        plan,
        per_query_limit=per_query_limit,
        source_mode=source_mode,
        source_configs=source_configs,
        enable_sources=enable_sources,
        disable_sources=disable_sources,
    )
    return papers


def search_all_with_diagnostics(
    plan: SearchPlan,
    per_query_limit: int = 10,
    *,
    source_mode: str = "auto",
    source_configs: dict[str, SourceConfig] | None = None,
    enable_sources: list[str] | None = None,
    disable_sources: list[str] | None = None,
) -> tuple[list[Paper], dict]:
    papers: list[Paper] = []
    source_configs = source_configs or {}
    source_names = resolve_enabled_sources(source_mode, source_configs, enable_sources, disable_sources)
    diagnostics = _init_diagnostics(source_names, source_configs, plan.search_queries)
    futures = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        for query in plan.search_queries:
            for source in source_names:
                cfg = source_configs.get(source)
                diagnostics["sources"][source]["queries"] += 1
                future = executor.submit(search_one_source, source, query, per_query_limit, plan.since_year, cfg)
                futures[future] = source
        for future in as_completed(futures):
            source = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                diagnostics["sources"][source]["status"] = "error"
                diagnostics["sources"][source]["errors"].append(f"{type(exc).__name__}: {exc}")
                continue
            diagnostics["sources"][source]["returned"] += len(result)
            diagnostics["sources"][source]["status"] = "ok"
            papers.extend(result)
    diagnostics["total_returned"] = len(papers)
    return papers, diagnostics


def search_one_source(
    source: str,
    query: str,
    limit: int,
    since_year: int | None,
    source_config: SourceConfig | None = None,
) -> list[Paper]:
    searcher = SEARCHERS.get(source)
    if not searcher:
        return []
    spec = SOURCE_SPECS[source]
    if spec.requires_key and not configured_api_key(source, source_config):
        return []
    return searcher(query, limit, since_year, source_config)


def search_arxiv(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
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


def search_semantic_scholar(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
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


def search_openalex(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
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


def search_crossref(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
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


def search_openreview(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
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


def search_pubmed(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    term = query
    if since_year:
        term = f"({query}) AND {since_year}:3000[pdat]"
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + encode_query(
        {"db": "pubmed", "term": term, "retmode": "json", "retmax": limit, "sort": "relevance"}
    )
    data = safe_fetch(lambda: request_json(search_url, timeout=12), {})
    ids = ((data.get("esearchresult") or {}).get("idlist") or []) if isinstance(data, dict) else []
    if not ids:
        return []
    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + encode_query(
        {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
    )
    text = safe_fetch(lambda: request_text(fetch_url, timeout=12), "")
    if not text:
        return []
    root = ET.fromstring(text)
    papers: list[Paper] = []
    for article in root.findall(".//PubmedArticle"):
        citation = article.find(".//MedlineCitation")
        pmid = _element_text(citation, "PMID") if citation is not None else None
        article_node = article.find(".//Article")
        title = compact_text(_element_text(article_node, "ArticleTitle"))
        abstract = compact_text(" ".join(node.text or "" for node in article.findall(".//AbstractText"))) or None
        authors = []
        for author in article.findall(".//Author"):
            name = " ".join(part for part in [_element_text(author, "ForeName"), _element_text(author, "LastName")] if part)
            if name:
                authors.append(name)
        year = _pubmed_year(article)
        journal = _element_text(article, ".//Journal/Title") or _element_text(article, ".//ISOAbbreviation")
        doi = None
        pmcid = None
        for aid in article.findall(".//ArticleId"):
            if aid.attrib.get("IdType") == "doi":
                doi = aid.text
            if aid.attrib.get("IdType") == "pmc":
                pmcid = aid.text
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None
        papers.append(
            Paper(
                title=title,
                authors=authors,
                year=year,
                venue=journal,
                abstract=abstract,
                doi=doi,
                url=url,
                source="pubmed",
                sources=["pubmed"],
                raw={"query": query, "identifiers": {"pmid": pmid, "pmcid": pmcid}},
            )
        )
    return [p for p in papers if p.title]


def search_europe_pmc(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    europe_query = query
    if since_year:
        europe_query = f'({query}) FIRST_PDATE:[{since_year}-01-01 TO 3000-12-31]'
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + encode_query(
        {"query": europe_query, "format": "json", "pageSize": limit, "resultType": "core"}
    )
    data = safe_fetch(lambda: request_json(url, timeout=12), {})
    results = (((data.get("resultList") or {}).get("result")) or []) if isinstance(data, dict) else []
    papers: list[Paper] = []
    for item in results:
        authors = [a.strip() for a in (item.get("authorString") or "").rstrip(".").split(",") if a.strip()]
        pmid = item.get("pmid")
        pmcid = item.get("pmcid")
        pdf_url = item.get("fullTextUrlList", {}).get("fullTextUrl", [{}])[0].get("url") if isinstance(item.get("fullTextUrlList"), dict) else None
        papers.append(
            Paper(
                title=compact_text(item.get("title")),
                authors=authors,
                year=_safe_int(str(item.get("pubYear") or "")),
                venue=item.get("journalTitle") or item.get("bookOrReportDetails"),
                abstract=compact_text(item.get("abstractText")),
                doi=item.get("doi"),
                url=item.get("doiUrl") or (f"https://europepmc.org/article/MED/{pmid}" if pmid else None),
                pdf_url=pdf_url,
                citation_count=_safe_int(item.get("citedByCount")),
                source="europe_pmc",
                sources=["europe_pmc"],
                raw={"query": query, "identifiers": {"pmid": pmid, "pmcid": pmcid}},
            )
        )
    return [p for p in papers if p.title]


def search_biorxiv(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    return _search_rxiv("biorxiv", query, limit, since_year)


def search_medrxiv(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    return _search_rxiv("medrxiv", query, limit, since_year)


def search_dblp(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    url = "https://dblp.org/search/publ/api?" + encode_query({"q": query, "format": "json", "h": limit})
    data = safe_fetch(lambda: request_json(url, timeout=12), {})
    hits = (((data.get("result") or {}).get("hits") or {}).get("hit") or []) if isinstance(data, dict) else []
    papers: list[Paper] = []
    for hit in hits:
        info = hit.get("info") or {}
        authors = _dblp_authors(info.get("authors"))
        year = _safe_int(info.get("year"))
        if since_year and year and year < since_year:
            continue
        papers.append(
            Paper(
                title=compact_text(info.get("title")),
                authors=authors,
                year=year,
                venue=info.get("venue"),
                doi=info.get("doi"),
                url=info.get("url"),
                source="dblp",
                sources=["dblp"],
                raw={"query": query, "identifiers": {"dblp_key": info.get("key")}},
            )
        )
    return [p for p in papers if p.title]


def search_acl_anthology(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    url = "https://aclanthology.org/search/?" + encode_query({"q": query})
    text = safe_fetch(lambda: request_text(url, timeout=12), "")
    papers: list[Paper] = []
    seen: set[str] = set()
    for match in re.finditer(r'href="(/(?:\d{4}\.)?[A-Z]\d{2,4}-[^\"]+/?)"[^>]*>(.*?)</a>', text, re.I | re.S):
        path, raw_title = match.groups()
        title = compact_text(re.sub("<[^>]+>", " ", html.unescape(raw_title)))
        if not title or title in seen:
            continue
        seen.add(title)
        year_match = re.search(r"/(\d{4})\.", path)
        year = _safe_int(year_match.group(1)) if year_match else None
        if since_year and year and year < since_year:
            continue
        papers.append(
            Paper(
                title=title,
                year=year,
                venue="ACL Anthology",
                url=f"https://aclanthology.org{path}",
                pdf_url=f"https://aclanthology.org{path.rstrip('/')}.pdf",
                source="acl_anthology",
                sources=["acl_anthology"],
                raw={"query": query},
            )
        )
        if len(papers) >= limit:
            break
    return papers


def search_papers_cool(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    per_source_limit = max(1, (limit + 1) // 2)
    papers: list[Paper] = []
    for source_mode in ("arxiv", "venue"):
        papers.extend(_search_papers_cool_list(source_mode, query, per_source_limit, since_year))
    return [p for p in papers if p.title][:limit]


def _search_papers_cool_list(source_mode: str, query: str, limit: int, since_year: int | None) -> list[Paper]:
    papers: list[Paper] = []
    seen: set[str] = set()
    per_page = min(20, max(1, limit))
    offset = 0
    max_pages = 2
    for _ in range(max_pages):
        fetch_limit = max(1, min(per_page, limit - len(papers)))
        if fetch_limit <= 0:
            break
        url = f"https://papers.cool/{source_mode}/search?" + encode_query(
            {
                "query": query,
                "skip": offset,
                "show": fetch_limit,
            }
        )
        text = safe_fetch(lambda: request_text(url, timeout=15), "")
        if not text:
            break
        parsed = _parse_papers_cool_html(text, query, source_mode=source_mode)
        if not parsed:
            break
        added = 0
        for paper in parsed:
            if since_year and paper.year and paper.year < since_year:
                continue
            if paper.doi:
                dedupe_key = f"doi::{paper.doi.lower()}"
            elif paper.arxiv_id:
                dedupe_key = f"arxiv::{paper.arxiv_id.lower()}"
            else:
                paperscope_id = (paper.raw.get("identifiers") or {}).get("papers_cool_id")
                dedupe_key = f"title::{paper.raw.get('query') or query}::{paper.title.lower()}"
                if paperscope_id:
                    dedupe_key = f"papers_cool::{paperscope_id}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            papers.append(paper)
            added += 1
        offset += fetch_limit
        if added < fetch_limit:
            break
        if len(papers) >= limit:
            break
        rate_limit_pause(0.35)
    return papers


def _parse_papers_cool_html(html_content: str, query: str, source_mode: str) -> list[Paper]:
    panels = re.finditer(
        r'<div id="(?P<paper_id>[^"]+)" class="panel paper"[^>]*>(?P<body>.*?)</div>',
        html_content,
        re.S,
    )
    papers: list[Paper] = []
    for match in panels:
        raw_id = match.group("paper_id")
        body = match.group("body")
        paper = _parse_papers_cool_panel(raw_id, body, query, source_mode)
        if paper:
            papers.append(paper)
    return papers



def _parse_papers_cool_panel(raw_id: str, body: str, query: str, source_mode: str) -> Paper | None:
    title = _extract_papers_cool_text(body, rf'title-{re.escape(raw_id)}"[^>]*>(?P<value>.*?)</a>')
    if not title:
        return None
    title = compact_text(title)
    if not title:
        return None

    link_match = re.search(rf'<a id="title-{re.escape(raw_id)}"[^>]*href="(?P<url>[^"]+)"', body)
    href = (link_match.group("url") if link_match else "").strip()
    url = _normalize_papers_cool_url(href)

    abstract = compact_text(_extract_papers_cool_text(body, rf'summary-{re.escape(raw_id)}"[^>]*>(?P<value>.*?)</p>'))
    authors = _extract_papers_cool_authors(raw_id, body)
    subjects = _extract_papers_cool_text(
        body,
        rf'subjects-{re.escape(raw_id)}"[^>]*>(?P<value>.*?)</p>',
        fallback="",
    )
    venue = _venue_from_papers_cool(source_mode, raw_id)
    pdf = re.search(rf'<a id="pdf-{re.escape(raw_id)}"[^>]*data="(?P<pdf>[^"]+)"', body)
    pdf_url = pdf.group("pdf").strip() if pdf else None
    date_text = _extract_papers_cool_text(
        body,
        rf'date-{re.escape(raw_id)}"[^>]*>(?P<value>.*?)</p>',
        fallback="",
    )
    year = None
    if date_text:
        date_match = re.search(r"(\d{4})", date_text)
        year = _safe_int(date_match.group(1)) if date_match else None
    if year is None and source_mode == "arxiv":
        arxiv_id_match = re.search(r"^(\d{4})\.\d+", raw_id)
        if arxiv_id_match:
            year = _safe_int(arxiv_id_match.group(1))
    if year is None and source_mode != "arxiv":
        fallback_match = re.search(r"^(\d{4})", raw_id) or re.search(r"\.(\d{4})", raw_id)
        year = _safe_int(fallback_match.group(1)) if fallback_match else None

    arxiv_id: str | None = None
    if source_mode == "arxiv":
        if href:
            arxiv_id = href.rstrip("/").rsplit("/", 1)[-1] if "/arxiv/" in href else None
        if not arxiv_id and re.match(r"^\d{4}\.\d{4,}(?:v\d+)?$", raw_id):
            arxiv_id = raw_id

    return Paper(
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        abstract=abstract or None,
        arxiv_id=arxiv_id,
        url=url,
        pdf_url=pdf_url,
        source="papers_cool",
        sources=["papers_cool"],
        raw={
            "query": query,
            "source_mode": source_mode,
            "identifiers": {
                "papers_cool_id": raw_id,
            },
            "subjects": [item for item in re.split(r",", subjects or "") if item.strip()],
        },
    )



def _extract_papers_cool_text(body: str, pattern: str, *, fallback: str = "") -> str:
    match = re.search(pattern, body, re.S)
    if not match:
        return fallback
    raw = match.group("value")
    text = re.sub(r"<[^>]+>", " ", raw)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return compact_text(html.unescape(text))


def _extract_papers_cool_authors(raw_id: str, body: str) -> list[str]:
    match = re.search(rf'authors-{re.escape(raw_id)}"[^>]*>(?P<value>.*?)</p>', body, re.S)
    if not match:
        return []
    raw = match.group("value")
    authors = [compact_text(html.unescape(name)) for name in re.findall(r'">([^<]+)</a>', raw)]
    if authors:
        return [author for author in authors if author]
    fallback = re.sub(r"<[^>]+>", ",", raw)
    return [compact_text(item) for item in fallback.split(",") if item.strip()]


def _normalize_papers_cool_url(path_or_url: str | None) -> str | None:
    if not path_or_url:
        return None
    value = path_or_url.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"https://papers.cool{value}" if value.startswith("/") else value


def _venue_from_papers_cool(source_mode: str, raw_id: str) -> str:
    if source_mode == "arxiv":
        return "arXiv"
    if "@" in raw_id:
        return raw_id.split("@", 1)[1]
    return source_mode


def search_core(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    api_key = configured_api_key("core", source_config)
    if not api_key:
        return []
    url = (source_config.base_url if source_config and source_config.base_url else "https://api.core.ac.uk/v3/search/works")
    url += "?" + encode_query({"q": query, "limit": limit})
    data = safe_fetch(lambda: request_json(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=12), {})
    results = data.get("results", []) if isinstance(data, dict) else []
    papers: list[Paper] = []
    for item in results:
        year = _safe_int(item.get("yearPublished") or item.get("year"))
        if since_year and year and year < since_year:
            continue
        authors = [a.get("name") for a in item.get("authors", []) if isinstance(a, dict) and a.get("name")]
        links = item.get("links") or []
        download_url = item.get("downloadUrl") or (links[0].get("url") if links and isinstance(links[0], dict) else None)
        papers.append(
            Paper(
                title=compact_text(item.get("title")),
                authors=authors,
                year=year,
                venue=item.get("publisher") or item.get("journals"),
                abstract=compact_text(item.get("abstract")),
                doi=item.get("doi"),
                url=item.get("sourceFulltextUrls", [None])[0] if isinstance(item.get("sourceFulltextUrls"), list) else item.get("url"),
                pdf_url=download_url,
                source="core",
                sources=["core"],
                raw={"query": query},
            )
        )
    return [p for p in papers if p.title]


def search_lens(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    api_key = configured_api_key("lens", source_config)
    if not api_key:
        return []
    payload = {
        "query": {"bool": {"must": [{"query_string": {"query": query}}]}},
        "size": limit,
    }
    data = safe_fetch(lambda: post_json("https://api.lens.org/scholarly/search", payload, headers={"Authorization": f"Bearer {api_key}"}, timeout=20), {})
    results = data.get("data", []) if isinstance(data, dict) else []
    papers: list[Paper] = []
    for item in results:
        year = _safe_int(item.get("year_published"))
        if since_year and year and year < since_year:
            continue
        authors = [a.get("display_name") for a in item.get("authors", []) if isinstance(a, dict) and a.get("display_name")]
        papers.append(
            Paper(
                title=compact_text(item.get("title")),
                authors=authors,
                year=year,
                venue=(item.get("source") or {}).get("title") if isinstance(item.get("source"), dict) else None,
                abstract=compact_text(item.get("abstract")),
                doi=(item.get("external_ids") or {}).get("doi") if isinstance(item.get("external_ids"), dict) else None,
                url=item.get("lens_url"),
                citation_count=_safe_int(item.get("scholarly_citations_count")),
                source="lens",
                sources=["lens"],
                raw={"query": query},
            )
        )
    return [p for p in papers if p.title]


def search_ieee(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    api_key = configured_api_key("ieee", source_config)
    if not api_key:
        return []
    url = "https://ieeexploreapi.ieee.org/api/v1/search/articles?" + encode_query(
        {"apikey": api_key, "format": "json", "querytext": query, "max_records": limit, "start_record": 1}
    )
    data = safe_fetch(lambda: request_json(url, timeout=12), {})
    papers = []
    for item in data.get("articles", []) if isinstance(data, dict) else []:
        year = _safe_int(item.get("publication_year"))
        if since_year and year and year < since_year:
            continue
        papers.append(
            Paper(
                title=compact_text(item.get("title")),
                authors=[a.get("full_name") for a in item.get("authors", {}).get("authors", []) if a.get("full_name")] if isinstance(item.get("authors"), dict) else [],
                year=year,
                venue=item.get("publication_title"),
                abstract=compact_text(item.get("abstract")),
                doi=item.get("doi"),
                url=item.get("html_url"),
                pdf_url=item.get("pdf_url"),
                citation_count=_safe_int(item.get("citing_paper_count")),
                source="ieee",
                sources=["ieee"],
                raw={"query": query},
            )
        )
    return [p for p in papers if p.title]


def search_springer(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    api_key = configured_api_key("springer", source_config)
    if not api_key:
        return []
    url = "https://api.springernature.com/meta/v2/json?" + encode_query({"q": query, "p": limit, "api_key": api_key})
    data = safe_fetch(lambda: request_json(url, timeout=12), {})
    papers = []
    for item in data.get("records", []) if isinstance(data, dict) else []:
        year = _safe_int(str(item.get("publicationDate", ""))[:4])
        if since_year and year and year < since_year:
            continue
        links = item.get("url") or []
        paper_url = links[0].get("value") if links and isinstance(links[0], dict) else None
        papers.append(
            Paper(
                title=compact_text(item.get("title")),
                authors=[a.get("creator") for a in item.get("creators", []) if isinstance(a, dict) and a.get("creator")],
                year=year,
                venue=item.get("publicationName"),
                abstract=compact_text(item.get("abstract")),
                doi=item.get("doi"),
                url=paper_url,
                source="springer",
                sources=["springer"],
                raw={"query": query},
            )
        )
    return [p for p in papers if p.title]


def search_elsevier(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    api_key = configured_api_key("elsevier", source_config)
    if not api_key:
        return []
    query_text = f"TITLE-ABS-KEY({query})"
    if since_year:
        query_text += f" AND PUBYEAR > {since_year - 1}"
    url = "https://api.elsevier.com/content/search/scopus?" + encode_query({"query": query_text, "count": limit})
    data = safe_fetch(lambda: request_json(url, headers={"X-ELS-APIKey": api_key}, timeout=12), {})
    entries = ((data.get("search-results") or {}).get("entry") or []) if isinstance(data, dict) else []
    papers = []
    for item in entries:
        papers.append(
            Paper(
                title=compact_text(item.get("dc:title")),
                authors=[item.get("dc:creator")] if item.get("dc:creator") else [],
                year=_safe_int(str(item.get("prism:coverDate", ""))[:4]),
                venue=item.get("prism:publicationName"),
                doi=item.get("prism:doi"),
                url=item.get("prism:url") or item.get("link", [{}])[0].get("@href") if isinstance(item.get("link"), list) else None,
                citation_count=_safe_int(item.get("citedby-count")),
                source="elsevier",
                sources=["elsevier"],
                raw={"query": query},
            )
        )
    return [p for p in papers if p.title]


def search_dimensions(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    api_key = configured_api_key("dimensions", source_config)
    if not api_key:
        return []
    year_filter = f" and year >= {since_year}" if since_year else ""
    payload = {"query": f'search publications for "\\"{query}\\""{year_filter} return publications[title+year+doi+abstract+authors+journal+times_cited+linkout] limit {limit}'}
    data = safe_fetch(lambda: post_json("https://app.dimensions.ai/api/dsl.json", payload, headers={"Authorization": f"Bearer {api_key}"}, timeout=20), {})
    papers = []
    for item in data.get("publications", []) if isinstance(data, dict) else []:
        papers.append(
            Paper(
                title=compact_text(item.get("title")),
                authors=[a.get("name") for a in item.get("authors", []) if isinstance(a, dict) and a.get("name")],
                year=_safe_int(item.get("year")),
                venue=(item.get("journal") or {}).get("title") if isinstance(item.get("journal"), dict) else None,
                abstract=compact_text(item.get("abstract")),
                doi=item.get("doi"),
                url=item.get("linkout"),
                citation_count=_safe_int(item.get("times_cited")),
                source="dimensions",
                sources=["dimensions"],
                raw={"query": query},
            )
        )
    return [p for p in papers if p.title]


def search_deepxiv(query: str, limit: int, since_year: int | None, source_config: SourceConfig | None = None) -> list[Paper]:
    api_key = configured_api_key("deepxiv", source_config)
    if not api_key:
        return []
    base_url = (source_config.base_url if source_config and source_config.base_url else "https://data.rag.ac.cn").rstrip("/")
    source_names = ["arxiv", "biorxiv", "medrxiv"]
    per_source_limit = max(1, min(limit, (limit + len(source_names) - 1) // len(source_names)))
    papers: list[Paper] = []
    for deepxiv_source in source_names:
        data = safe_fetch(
            lambda source=deepxiv_source: _deepxiv_sdk_search(
                query,
                per_source_limit,
                since_year,
                source,
                api_key,
                base_url,
            ),
            {},
        )
        if not data:
            data = safe_fetch(
                lambda source=deepxiv_source: _deepxiv_rest_search(
                    query,
                    per_source_limit,
                    since_year,
                    source,
                    api_key,
                    base_url,
                ),
                {},
            )
        papers.extend(_deepxiv_papers_from_response(data, query, deepxiv_source))
    return [p for p in papers if p.title][: max(1, limit)]


def _deepxiv_sdk_search(
    query: str,
    limit: int,
    since_year: int | None,
    source: str,
    api_key: str,
    base_url: str,
) -> dict:
    from deepxiv_sdk import Reader

    reader = Reader(token=api_key, base_url=base_url, timeout=18, max_retries=1)
    kwargs = {"date_from": f"{since_year}-01-01"} if since_year else {}
    return reader.search(query, size=limit, source=source, use_fine_rerank=True, **kwargs)


def _deepxiv_rest_search(
    query: str,
    limit: int,
    since_year: int | None,
    source: str,
    api_key: str,
    base_url: str,
) -> dict:
    params = {
        "type": "retrieve",
        "query": query,
        "source": source,
        "top_k": limit,
        "use_fine_rerank": "true",
    }
    if since_year:
        params["date_search_type"] = "after"
        params["date_str"] = f"{since_year}-01-01"
    url = f"{base_url}/arxiv/?" + encode_query(params)
    return request_json(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=18)


def _deepxiv_papers_from_response(data: dict, query: str, deepxiv_source: str) -> list[Paper]:
    if not isinstance(data, dict):
        return []
    results = data.get("result") or data.get("results") or []
    if not isinstance(results, list):
        return []
    papers: list[Paper] = []
    id_field = f"{deepxiv_source}_id"
    for item in results:
        if not isinstance(item, dict):
            continue
        paper_id = item.get(id_field) or item.get("arxiv_id") or item.get("id")
        doi = item.get("doi")
        if not doi and deepxiv_source in {"biorxiv", "medrxiv"} and isinstance(paper_id, str) and paper_id.startswith("10."):
            doi = paper_id
        url = item.get("url") or item.get("paper_url")
        if not url and deepxiv_source == "arxiv" and paper_id:
            url = f"https://arxiv.org/abs/{paper_id}"
        authors = _deepxiv_authors(item.get("authors"))
        year = _safe_int(str(item.get("date") or item.get("publish_at") or "")[:4])
        pdf_url = item.get("pdf_url") or item.get("src_url")
        if not pdf_url and deepxiv_source == "arxiv" and paper_id:
            pdf_url = f"https://arxiv.org/pdf/{paper_id}"
        papers.append(
            Paper(
                title=compact_text(item.get("title")),
                authors=authors,
                year=year,
                venue=f"DeepXiv {deepxiv_source}",
                abstract=compact_text(item.get("abstract") or item.get("tldr")),
                doi=doi,
                arxiv_id=str(paper_id) if deepxiv_source == "arxiv" and paper_id else None,
                url=url,
                pdf_url=pdf_url,
                citation_count=_safe_int(item.get("citation_count") or item.get("citations")),
                source="deepxiv",
                sources=["deepxiv"],
                raw={
                    "query": query,
                    "deepxiv_source": deepxiv_source,
                    "identifiers": {id_field: paper_id} if paper_id else {},
                    "score": item.get("score"),
                    "categories": item.get("categories"),
                },
            )
        )
    return [p for p in papers if p.title]


def _deepxiv_authors(value) -> list[str]:
    if isinstance(value, list):
        authors = []
        for item in value:
            if isinstance(item, dict) and item.get("name"):
                authors.append(item["name"])
            elif isinstance(item, str):
                authors.append(item)
        return authors
    if isinstance(value, str):
        return [part.strip() for part in re.split(r";|,", value) if part.strip()]
    return []


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


def _search_rxiv(server: str, query: str, limit: int, since_year: int | None) -> list[Paper]:
    today = dt.date.today().isoformat()
    start = f"{since_year or dt.date.today().year - 2}-01-01"
    url = f"https://api.biorxiv.org/details/{server}/{start}/{today}/0"
    data = safe_fetch(lambda: request_json(url, timeout=18), {})
    collection = data.get("collection", []) if isinstance(data, dict) else []
    terms = [token for token in re.findall(r"[a-zA-Z0-9]+", query.lower()) if len(token) > 2]
    papers: list[Paper] = []
    for item in collection:
        text = " ".join([item.get("title") or "", item.get("abstract") or ""]).lower()
        if terms and not any(term in text for term in terms):
            continue
        year = _safe_int(str(item.get("date", ""))[:4])
        doi = item.get("doi")
        papers.append(
            Paper(
                title=compact_text(item.get("title")),
                authors=[a.strip() for a in (item.get("authors") or "").split(";") if a.strip()],
                year=year,
                venue=server,
                abstract=compact_text(item.get("abstract")),
                doi=doi,
                url=f"https://doi.org/{doi}" if doi else None,
                pdf_url=f"https://www.{server}.org/content/{doi}v{item.get('version', '1')}.full.pdf" if doi else None,
                source=server,
                sources=[server],
                raw={"query": query, "server": server},
            )
        )
        if len(papers) >= limit:
            break
    return [p for p in papers if p.title]


def _element_text(node: ET.Element | None, path: str) -> str | None:
    if node is None:
        return None
    value = node.findtext(path)
    return compact_text(value) if value else None


def _pubmed_year(article: ET.Element) -> int | None:
    for path in [".//ArticleDate/Year", ".//PubDate/Year", ".//PubMedPubDate[@PubStatus='pubmed']/Year"]:
        year = _safe_int(_element_text(article, path))
        if year:
            return year
    medline_date = _element_text(article, ".//PubDate/MedlineDate") or ""
    match = re.search(r"\d{4}", medline_date)
    return _safe_int(match.group(0)) if match else None


def _dblp_authors(value) -> list[str]:
    if isinstance(value, dict):
        author = value.get("author")
        if isinstance(author, list):
            return [item.get("text") if isinstance(item, dict) else str(item) for item in author if item]
        if isinstance(author, dict):
            return [author.get("text") or ""]
        if isinstance(author, str):
            return [author]
    return []


def _safe_int(value) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _init_diagnostics(source_names: list[str], source_configs: dict[str, SourceConfig], queries: list[str]) -> dict:
    sources = {}
    for name in source_names:
        spec = SOURCE_SPECS[name]
        cfg = source_configs.get(name)
        sources[name] = {
            "display_name": spec.display_name,
            "domain": spec.domain,
            "requires_key": spec.requires_key,
            "configured": bool(configured_api_key(name, cfg)),
            "queries": 0,
            "returned": 0,
            "status": "pending",
            "errors": [],
        }
    return {
        "enabled_sources": source_names,
        "query_count": len(queries),
        "total_returned": 0,
        "sources": sources,
    }


SEARCHERS = {
    "arxiv": search_arxiv,
    "semantic_scholar": search_semantic_scholar,
    "openalex": search_openalex,
    "crossref": search_crossref,
    "openreview": search_openreview,
    "pubmed": search_pubmed,
    "europe_pmc": search_europe_pmc,
    "biorxiv": search_biorxiv,
    "medrxiv": search_medrxiv,
    "dblp": search_dblp,
    "acl_anthology": search_acl_anthology,
    "papers_cool": search_papers_cool,
    "core": search_core,
    "lens": search_lens,
    "ieee": search_ieee,
    "springer": search_springer,
    "elsevier": search_elsevier,
    "dimensions": search_dimensions,
    "deepxiv": search_deepxiv,
}


def iter_search_errors(_: Iterable[Paper]) -> list[str]:
    return []
