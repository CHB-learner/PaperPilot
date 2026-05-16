from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from jinja2 import Template

from .models import CorpusItem, Paper, QualityGate, ResearchProtocol, SearchPlan, VerificationRecord
from .openai_client import OpenAIClient
from .prompts import run_prompt_json
from .query import QueryUnderstanding
from .synthesis import synthesis_summary_counts


def build_canonical_report(
    understanding: QueryUnderstanding,
    plan: SearchPlan,
    protocol: ResearchProtocol,
    report_items: list[CorpusItem],
    core_items: list[CorpusItem],
    adjacent_items: list[CorpusItem],
    excluded_items: list[CorpusItem],
    literature_matrix: list[dict[str, Any]],
    synthesis: dict[str, Any],
    verification: list[VerificationRecord],
    quality_gate: QualityGate,
    download_log: list[dict],
    reflection: dict,
    evidence_ledger: dict[str, Any] | None = None,
    review_agents: dict[str, Any] | None = None,
    source_diagnostics: dict[str, Any] | None = None,
    *,
    mode: str,
    include_adjacent: bool,
    client: OpenAIClient | None,
) -> dict[str, Any]:
    papers = [_paper_entry(item, idx) for idx, item in enumerate(report_items, start=1)]
    citation_map = {paper["citation_key"]: paper for paper in papers}
    title_citation_map = {_normalize_title_for_match(paper["title"]): paper for paper in papers}
    matrix_by_key = {row.get("citation_key"): row for row in literature_matrix}
    for paper in papers:
        row = matrix_by_key.get(paper["citation_key"])
        if row:
            paper["method_category"] = row.get("method_category", "")
            paper["task"] = row.get("task", "")
    adjacent = [_paper_entry(item, idx) for idx, item in enumerate(adjacent_items, start=1)] if include_adjacent else []
    report_keys = {paper["citation_key"] for paper in papers}
    paper_summaries = [
        _with_summary_citation(summary, citation_map)
        for summary in synthesis.get("paper_summaries", [])
        if summary.get("citation_key") in report_keys
    ]
    if len(paper_summaries) < len(report_items):
        paper_summaries = _ensure_report_summaries(report_items, synthesis.get("paper_summaries", []), citation_map, paper_summaries)
    method_taxonomy = _with_representative_citations(
        synthesis.get("method_taxonomy", synthesis.get("themes", [])),
        citation_map,
    )
    method_comparison = _with_comparison_citations(synthesis.get("method_comparison", []), citation_map)
    literature_matrix = [_with_matrix_citation(row, citation_map) for row in literature_matrix]
    evidence_map = _normalize_evidence_map(synthesis.get("evidence_map", []), citation_map)
    verification_by_key = {record.citation_key: record.to_dict() for record in verification}
    pdf_summary = summarize_downloads(download_log)
    _with_download_citations(pdf_summary, title_citation_map)
    canonical = {
        "title": f"Literature Review: {understanding.original_keyword}",
        "title_zh": f"{understanding.original_keyword} 文献综述",
        "report_date": datetime.now().date().isoformat(),
        "mode": mode,
        "query": {
            "original": understanding.original_keyword,
            "recommended": plan.recommended_query,
            "interpretations": understanding.possible_interpretations,
            "included_scope": understanding.included_scope,
            "excluded_scope": understanding.excluded_scope,
            "search_queries": plan.search_queries,
        },
        "protocol": protocol.to_dict(),
        "prisma": {
            "identified": quality_gate.metrics.get("total_candidates", 0),
            "after_dedup": quality_gate.metrics.get("dedup", {}).get("after_title_similarity_dedup", 0),
            "core": len(core_items),
            "adjacent": len(adjacent_items),
            "excluded": len(excluded_items),
            "reported": len(report_items),
        },
        "minimum_report_policy": {
            "min_report_papers": quality_gate.metrics.get("min_report_papers", 0),
            "final_report_count": quality_gate.metrics.get("final_report_count", len(report_items)),
            "core_report_count": quality_gate.metrics.get("core_report_count", len(report_items)),
            "adjacent_report_count": quality_gate.metrics.get("adjacent_report_count", 0),
            "minimum_fill_count": quality_gate.metrics.get("minimum_fill_count", 0),
            "code_filter_fallback_count": quality_gate.metrics.get("code_filter_fallback_count", 0),
            "adjacent_fill_count": quality_gate.metrics.get("adjacent_fill_count", 0),
            "selection_policy": quality_gate.metrics.get("selection_policy", "core_first"),
        },
        "quality_gate": quality_gate.to_dict(),
        "papers": papers,
        "citation_map": {key: _citation_reference(paper) for key, paper in citation_map.items()},
        "adjacent_papers": adjacent,
        "method_counts": synthesis_summary_counts(literature_matrix),
        "literature_matrix": literature_matrix,
        "synthesis": synthesis,
        "field_overview": synthesis.get("field_overview", {}),
        "method_taxonomy": method_taxonomy,
        "research_questions": synthesis.get("field_overview", {}).get("research_questions", []),
        "paper_summaries": paper_summaries,
        "method_comparison": method_comparison,
        "research_trends": synthesis.get("research_trends", synthesis.get("method_evolution", [])),
        "research_trends_with_evidence": _attach_claim_references(synthesis.get("research_trends", []), citation_map),
        "evidence_map": evidence_map,
        "verification": verification_by_key,
        "pdf_summary": pdf_summary,
        "download_log": download_log,
        "source_diagnostics": source_diagnostics or {},
        "source_coverage": _source_coverage(source_diagnostics),
        "reflection": reflection,
        "evidence_ledger": evidence_ledger or {},
        "review_agents": review_agents or {},
        "limitations": _limitations(protocol, quality_gate, pdf_summary),
        "ai_disclosure": (
            "This report was produced with AI-assisted research tools. The pipeline included AI-powered "
            "query understanding, literature search planning, corpus screening, evidence synthesis, and report drafting. "
            "Findings are limited to the retrieved metadata, abstracts, verified links, and downloaded open-access PDFs."
        ),
    }
    canonical["abstract"] = _abstract(canonical, client)
    return canonical


def render_reports(canonical: dict[str, Any]) -> tuple[str, str]:
    return (
        _compact_markdown_table_gaps(Template(ZH_TEMPLATE).render(report=canonical)),
        _compact_markdown_table_gaps(Template(EN_TEMPLATE).render(report=canonical)),
    )


def render_html_reports(canonical: dict[str, Any]) -> tuple[str, str]:
    zh_md, en_md = render_reports(canonical)
    return (
        markdown_report_to_html(zh_md, title=canonical["title_zh"], lang="zh-CN"),
        markdown_report_to_html(en_md, title=canonical["title"], lang="en"),
    )


def write_reports(
    understanding: QueryUnderstanding,
    plan: SearchPlan,
    papers: list[Paper],
    download_log: list[dict],
    reflection: dict,
    client: OpenAIClient | None,
) -> tuple[str, str]:
    """Backward-compatible fallback used by older callers and tests."""
    from .corpus import CorpusItem, classify_paper, code_artifacts_for_paper
    from .models import ResearchProtocol
    from .protocol import build_protocol
    from .verification import build_quality_gate, verify_corpus
    from .synthesis import build_literature_matrix, build_synthesis

    protocol = build_protocol(understanding, plan, "any", client=None)
    items = [
        CorpusItem(
            citation_key=f"paper{i}",
            paper=paper,
            inclusion=classify_paper(paper, plan, protocol),
            code_artifacts=code_artifacts_for_paper(paper),
        )
        for i, paper in enumerate(papers, start=1)
    ]
    core = [item for item in items if item.inclusion.label == "core"] or items
    adjacent = [item for item in items if item.inclusion.label == "adjacent"]
    excluded = [item for item in items if item.inclusion.label == "exclude"]
    verification = verify_corpus(items, download_log)
    matrix = build_literature_matrix(core)
    quality = build_quality_gate(
        items,
        core,
        verification,
        download_log,
        max_papers=plan.max_papers,
        github_filter="any",
        quality="balanced",
        dedup_stats={"raw_count": len(papers), "after_title_similarity_dedup": len(papers)},
    )
    synthesis = build_synthesis(core, adjacent, matrix, plan, protocol, client=None)
    canonical = build_canonical_report(
        understanding,
        plan,
        protocol,
        core,
        core,
        adjacent,
        excluded,
        matrix,
        synthesis,
        verification,
        quality,
        download_log,
        reflection,
        mode="apa",
        include_adjacent=False,
        client=client,
    )
    return render_reports(canonical)


def _paper_entry(item: CorpusItem, index: int) -> dict[str, Any]:
    paper = item.paper
    reference_link = _paper_reference_link(paper.doi, paper.url)
    return {
        "index": index,
        "citation_label": f"[{index}]",
        "citation_key": item.citation_key,
        "title": paper.title,
        "display_title": f"[{index}] {paper.title}",
        "authors": paper.authors,
        "author_text": _author_text(paper.authors),
        "year": paper.year or "n.d.",
        "venue": paper.venue or "",
        "doi": paper.doi or "",
        "url": paper.url or "",
        "reference_link": reference_link,
        "reference_link_markdown": f"[{reference_link}]({reference_link})" if reference_link else "",
        "pdf_url": paper.pdf_url or "",
        "citation_count": paper.citation_count or 0,
        "rank_score": paper.rank_score,
        "relevance_score": paper.relevance_score,
        "inclusion_score": item.inclusion.score,
        "inclusion_reason": item.inclusion.reason,
        "report_role": (paper.raw or {}).get("report_role", "core"),
        "report_tier": (paper.raw or {}).get("report_tier", item.inclusion.label),
        "report_selection_reason": (paper.raw or {}).get("report_selection_reason", ""),
        "method_category": "",
        "code_url": paper.github_url or paper.code_url or "",
        "code_confidence": max((artifact.confidence for artifact in item.code_artifacts), default=0.0),
        "sources": sorted(set(paper.sources or [paper.source])),
    }


def _paper_reference_link(doi: str | None, url: str | None) -> str:
    if doi:
        value = doi.strip()
        if value.startswith(("http://", "https://")):
            return value
        return f"https://doi.org/{value}"
    return (url or "").strip()


def _citation_reference(paper: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": paper["index"],
        "citation_label": paper["citation_label"],
        "title": paper["title"],
        "display_title": paper["display_title"],
        "code_url": paper.get("code_url", ""),
        "pdf_url": paper.get("pdf_url", ""),
        "url": paper.get("url", ""),
        "doi": paper.get("doi", ""),
        "reference_link": paper.get("reference_link", ""),
    }


def _with_summary_citation(summary: dict[str, Any], citation_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result = dict(summary)
    paper = citation_map.get(str(summary.get("citation_key")))
    if paper:
        result["index"] = paper["index"]
        result["citation_label"] = paper["citation_label"]
        result["display_title"] = paper["display_title"]
        result["code_url"] = result.get("code_url") or paper.get("code_url", "")
        result["pdf_url"] = result.get("pdf_url") or paper.get("pdf_url", "")
    else:
        result.setdefault("citation_label", "")
        result.setdefault("display_title", result.get("title", ""))
    return result


def _with_representative_citations(methods: list[dict[str, Any]], citation_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for method in methods:
        if not isinstance(method, dict):
            continue
        result = dict(method)
        result["representative_paper_refs"] = _format_representative_refs(result.get("representative_papers"), citation_map)
        enriched.append(result)
    return enriched


def _ensure_report_summaries(
    report_items: list[dict[str, Any]],
    raw_summaries: list[dict[str, Any]],
    citation_map: dict[str, dict[str, Any]],
    already_present: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    present_keys = {summary.get("citation_key") for summary in already_present}
    for paper in report_items:
        key = paper["citation_key"]
        if key in present_keys:
            continue
        fallback = {
            "citation_key": key,
            "title": paper["title"],
            "research_question": "MATERIAL GAP",
            "task_definition": "No structured task statement extracted in current synthesis.",
            "task": "Open interpretation",
            "method": "MATERIAL GAP",
            "contributions": "MATERIAL GAP",
            "results_signal": "MATERIAL GAP",
            "reproducibility": f"Code: {'found' if paper['code_url'] else 'not found'}, PDF: {'found' if paper['pdf_url'] else 'not found'}.",
            "evidence_basis": "metadata_or_abstract_only",
            "limitations": ["No full synthesis sentence was generated; claim should be treated cautiously."],
        }
        fallback.update(_with_summary_citation(fallback, citation_map))
        already_present.append(fallback)
    return already_present


def _normalize_evidence_map(
    evidence_map: list[dict[str, Any]],
    citation_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(evidence_map, start=1):
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        if not claim:
            continue
        refs = _map_evidence_refs(item.get("citation_keys") or item.get("citations", []), citation_map)
        normalized.append(
            {
                "claim_id": str(item.get("claim_id") or f"claim_{idx}"),
                "claim": claim,
                "citation_refs": refs or [""],
                "citation_keys": [key for key in item.get("citation_keys", []) if key],
                "strength": (str(item.get("strength") or "moderate")).lower(),
                "evidence_basis": str(item.get("basis") or item.get("evidence_basis") or "synthesis"),
            }
        )
    return normalized


def _attach_claim_references(trends: list[str], citation_map: dict[str, dict[str, Any]]) -> list[str]:
    if not trends:
        return []
    return [f"{trend}" for trend in trends]


def _map_evidence_refs(refs: Any, citation_map: dict[str, dict[str, Any]]) -> list[str]:
    if isinstance(refs, str):
        candidate_keys = [item.strip() for item in refs.split(",") if item.strip()]
    elif isinstance(refs, list):
        candidate_keys = [str(item).strip() for item in refs if str(item).strip()]
    else:
        candidate_keys = []
    resolved = []
    for key in candidate_keys:
        paper = citation_map.get(key)
        if not paper:
            paper = citation_map.get(_normalize_title_for_match(key))
        if paper:
            resolved.append(paper["citation_label"])
        else:
            if key:
                resolved.append(key)
    deduped = list(dict.fromkeys(resolved))
    return deduped


def _with_comparison_citations(rows: list[dict[str, Any]], citation_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        result = dict(row)
        result["representative_paper_refs"] = _format_representative_refs(result.get("representative_papers"), citation_map)
        enriched.append(result)
    return enriched


def _format_representative_refs(value: Any, citation_map: dict[str, dict[str, Any]]) -> list[str]:
    if not value:
        return []
    values = value if isinstance(value, list) else re.split(r"[,;]\s*", str(value).strip("[]"))
    refs = []
    for raw in values:
        key = str(raw).strip().strip("'\"")
        if not key:
            continue
        paper = citation_map.get(key)
        if paper:
            refs.append(paper["display_title"])
        else:
            refs.append(key)
    return list(dict.fromkeys(refs))


def _with_matrix_citation(row: dict[str, Any], citation_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result = dict(row)
    paper = citation_map.get(str(row.get("citation_key")))
    if paper:
        result["citation_label"] = paper["citation_label"]
        result["display_title"] = paper["display_title"]
    else:
        result["citation_label"] = ""
        result["display_title"] = str(row.get("title") or row.get("citation_key") or "")
    return result


def _with_download_citations(pdf_summary: dict[str, Any], title_citation_map: dict[str, dict[str, Any]]) -> None:
    for item in pdf_summary.get("items", []):
        paper = title_citation_map.get(_normalize_title_for_match(item.get("title", "")))
        if paper:
            item["citation_label"] = paper["citation_label"]
            item["display_title"] = paper["display_title"]
        else:
            item["citation_label"] = ""
            item["display_title"] = item.get("title", "")


def _normalize_title_for_match(title: str) -> str:
    return re.sub(r"\W+", " ", str(title).lower()).strip()


def summarize_downloads(download_log: list[dict]) -> dict[str, Any]:
    summary = {"downloaded": 0, "skipped": 0, "failed": 0, "items": []}
    for item in download_log:
        status = item.get("status")
        if status in summary:
            summary[status] += 1
        summary["items"].append(
            {
                "title": item.get("title"),
                "status": status,
                "reason": item.get("reason", ""),
                "path": item.get("path", ""),
                "url": item.get("url", ""),
            }
        )
    return summary


def _abstract(canonical: dict[str, Any], client: OpenAIClient | None) -> dict[str, str]:
    fallback_en = (
        f"This APA-style literature review examines {canonical['query']['original']} using "
        f"{canonical['prisma']['reported']} reported papers selected from {canonical['prisma']['identified']} retrieved candidates. "
        "The report emphasizes verified metadata, code availability, open PDF access, method evolution, and corpus limitations."
    )
    fallback_zh = (
        f"本综述围绕 {canonical['query']['original']} 展开，从 {canonical['prisma']['identified']} 条候选记录中筛选出 "
        f"{canonical['prisma']['reported']} 篇进入报告。报告重点覆盖方法演进、代码可用性、开放 PDF、证据限制和后续研究方向。"
    )
    if not client or not client.available:
        return {"en": fallback_en, "zh": fallback_zh}
    payload = run_prompt_json(
        client,
        "abstract",
        fallback={"zh": fallback_zh, "en": fallback_en},
        title=canonical["title"],
        prisma=canonical["prisma"],
        themes=canonical["synthesis"].get("themes"),
        field_overview=canonical.get("field_overview"),
        limitations=canonical["limitations"],
    )
    return {"zh": str(payload.get("zh") or fallback_zh), "en": str(payload.get("en") or fallback_en)}


def _limitations(protocol: ResearchProtocol, quality_gate: QualityGate, pdf_summary: dict[str, Any]) -> list[str]:
    limitations = [
        "The review uses retrieved metadata, abstracts, and downloaded open-access PDFs; unavailable full texts are not treated as verified evidence.",
        f"PDF downloads: {pdf_summary['downloaded']} downloaded, {pdf_summary['skipped']} skipped, {pdf_summary['failed']} failed.",
    ]
    if protocol.github_filter == "required":
        limitations.append("GitHub filter mode was `required` and may bias the final view toward papers with public implementations.")
    elif protocol.github_filter == "none":
        limitations.append("GitHub filter mode was `none` and may bias the final view toward papers without public code links.")
    limitations.extend(quality_gate.issues)
    return list(dict.fromkeys(limitations))


def _source_coverage(source_diagnostics: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not source_diagnostics:
        return []
    coverage = []
    for name, info in (source_diagnostics.get("sources") or {}).items():
        coverage.append(
            {
                "name": name,
                "display_name": info.get("display_name") or name,
                "domain": info.get("domain") or "",
                "status": info.get("status") or "unknown",
                "queries": info.get("queries") or 0,
                "returned": info.get("returned") or 0,
                "errors": len(info.get("errors") or []),
            }
        )
    return coverage


def _author_text(authors: list[str]) -> str:
    if not authors:
        return "Unknown author"
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} & {authors[1]}"
    return f"{authors[0]} et al."


def md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def markdown_report_to_html(markdown_text: str, *, title: str, lang: str) -> str:
    markdown_text = _compact_markdown_table_gaps(markdown_text)
    body: list[str] = []
    table_rows: list[list[str]] = []
    list_items: list[str] = []

    def flush_table() -> None:
        nonlocal table_rows
        if not table_rows:
            return
        header, *rows = table_rows
        body.append("<div class=\"table-wrap\"><table>")
        body.append("<thead><tr>" + "".join(f"<th>{_inline_html(cell)}</th>" for cell in header) + "</tr></thead>")
        if rows:
            body.append("<tbody>")
            for row in rows:
                cells = row + [""] * (len(header) - len(row))
                body.append("<tr>" + "".join(f"<td>{_inline_html(cell)}</td>" for cell in cells[: len(header)]) + "</tr>")
            body.append("</tbody>")
        body.append("</table></div>")
        table_rows = []

    def flush_list() -> None:
        nonlocal list_items
        if not list_items:
            return
        body.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_items) + "</ul>")
        list_items = []

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("|"):
            flush_list()
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not _is_markdown_separator(cells):
                table_rows.append(cells)
            continue
        flush_table()
        if not line:
            flush_list()
            continue
        if line.startswith("- "):
            list_items.append(_inline_html(line[2:]))
            continue
        flush_list()
        if line.startswith("#"):
            level = min(4, len(line) - len(line.lstrip("#")))
            text = line[level:].strip()
            body.append(f"<h{level}>{_inline_html(text)}</h{level}>")
        else:
            body.append(f"<p>{_inline_html(line)}</p>")
    flush_table()
    flush_list()

    return HTML_SHELL.format(
        lang=html.escape(lang, quote=True),
        title=html.escape(title),
        body="\n".join(body),
    )


def _compact_markdown_table_gaps(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    compacted: list[str] = []
    for index, line in enumerate(lines):
        if line.strip():
            compacted.append(line)
            continue
        previous_is_table = bool(compacted) and compacted[-1].lstrip().startswith("|")
        next_nonempty = next((candidate for candidate in lines[index + 1 :] if candidate.strip()), "")
        next_is_table = next_nonempty.lstrip().startswith("|")
        if previous_is_table and next_is_table:
            continue
        compacted.append(line)
    return "\n".join(compacted).strip() + "\n"


def _inline_html(text: Any) -> str:
    raw = str(text)
    raw = re.sub(r"`([^`]+)`", r"\1", raw)
    raw = re.sub(r"\*\*([^*]+)\*\*", r"\1", raw)
    raw = re.sub(r"\*([^*]+)\*", r"\1", raw)
    parts: list[str] = []
    pos = 0
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", raw):
        parts.append(html.escape(raw[pos : match.start()]))
        label = html.escape(match.group(1))
        url = html.escape(match.group(2), quote=True)
        parts.append(f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>')
        pos = match.end()
    parts.append(html.escape(raw[pos:]))
    return "".join(parts)


def _is_markdown_separator(cells: list[str]) -> bool:
    return bool(cells) and all(set(cell) <= {"-", ":", " "} for cell in cells)


HTML_SHELL = """<!doctype html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #172033;
      --muted: #5b6472;
      --line: #d8dee8;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --accent: #1f6feb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--bg);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
      line-height: 1.58;
    }}
    main {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 34px 18px 48px;
    }}
    h1, h2, h3, h4 {{
      letter-spacing: 0;
      line-height: 1.25;
      color: var(--ink);
    }}
    h1 {{
      margin: 0 0 16px;
      padding-bottom: 14px;
      border-bottom: 2px solid var(--line);
      font-size: 30px;
    }}
    h2 {{
      margin: 30px 0 12px;
      padding-top: 10px;
      border-top: 1px solid var(--line);
      font-size: 22px;
    }}
    h3 {{ margin: 22px 0 9px; font-size: 18px; }}
    h4 {{ margin: 18px 0 7px; font-size: 15px; }}
    p, li {{ font-size: 14px; color: var(--muted); }}
    p {{ margin: 8px 0; }}
    ul {{ margin: 8px 0 12px; padding-left: 22px; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{
      padding: 1px 4px;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: #f8fafc;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.92em;
      color: #1f2937;
    }}
    .table-wrap {{
      width: 100%;
      overflow-x: auto;
      margin: 12px 0 18px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 1px 0 rgba(23, 32, 51, 0.02);
    }}
    table {{
      width: 100%;
      min-width: 760px;
      table-layout: fixed;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      word-wrap: break-word;
      word-break: break-word;
    }}
    th {{
      color: var(--ink);
      background: #eef2f7;
      font-weight: 700;
    }}
    td {{ color: var(--muted); }}
    tr:last-child td {{ border-bottom: 0; }}
    @media (max-width: 760px) {{
      main {{ padding: 24px 12px 36px; }}
      h1 {{ font-size: 24px; }}
      h2 {{ font-size: 19px; }}
    }}
  </style>
</head>
<body>
  <main>
{body}
  </main>
</body>
</html>
"""


ZH_TEMPLATE = r"""# {{ report.title_zh }}

**生成日期**: {{ report.report_date }}  
**报告模式**: {{ report.mode }}  
**质量门结论**: {{ report.quality_gate.verdict }}

## 摘要

{{ report.abstract.zh }}

**关键词**: {{ report.query.search_queries[:6] | join(", ") }}

## 1. 查询解释与研究协议

原始需求：`{{ report.query.original }}`  
推荐检索式：`{{ report.query.recommended }}`

研究问题：{{ report.protocol.research_question }}

### 纳入标准
{% for item in report.protocol.inclusion_criteria %}
- {{ item }}
{% endfor %}

### 排除标准
{% for item in report.protocol.exclusion_criteria %}
- {{ item }}
{% endfor %}

## 2. 检索与筛选方法

| 阶段 | 数量 |
|---|---:|
| 初始候选记录 | {{ report.prisma.identified }} |
| 去重后记录 | {{ report.prisma.after_dedup }} |
| 核心论文 | {{ report.prisma.core }} |
| 相关但非核心 | {{ report.prisma.adjacent }} |
| 排除记录 | {{ report.prisma.excluded }} |
| 进入报告 | {{ report.prisma.reported }} |

检索来源：{{ report.protocol.search_sources | join(", ") }}。开放 PDF 只在明确可访问时下载，不绕过付费墙。

### 报告论文数量策略

本报告默认不强制最低论文篇数，按相关性优先纳入核心论文，并在不超过用户设置上限的前提下补充相关但非核心论文。若用户显式设置 `--min-report-papers`，系统会尝试用相关论文补齐并标注补齐来源。

| 指标 | 数量 |
|---|---:|
| 进入报告总数 | {{ report.minimum_report_policy.final_report_count }} |
| 用户设置最低篇数 | {{ report.minimum_report_policy.min_report_papers }} |
| 核心论文 | {{ report.minimum_report_policy.core_report_count }} |
| 相关补齐论文 | {{ report.minimum_report_policy.adjacent_report_count }} |
| 代码筛选 fallback | {{ report.minimum_report_policy.code_filter_fallback_count }} |
| 最低数量补齐 | {{ report.minimum_report_policy.minimum_fill_count }} |

### 来源覆盖情况

| 来源 | 领域 | 状态 | 查询数 | 返回数 | 错误数 |
|---|---|---|---:|---:|---:|
{% for source in report.source_coverage %}
| {{ source.display_name }} | {{ source.domain }} | {{ source.status }} | {{ source.queries }} | {{ source.returned }} | {{ source.errors }} |
{% endfor %}

## 3. 研究背景与问题定义

{{ report.field_overview.background }}

{{ report.field_overview.problem_definition }}

{{ report.field_overview.why_it_matters }}

### 研究问题（RQ）
{% for item in report.field_overview.research_questions %}
- {{ item }}
{% endfor %}

### 证据范围
**证据范围说明**: {{ report.field_overview.scope_note }}
**适用领域**: {{ report.field_overview.applicable_domains | join(", ") }}

## 4. 主流方法流派综述

{% for method in report.method_taxonomy %}
### {{ loop.index }}. {{ method.name }}

**核心思想**: {{ method.core_idea }}

**典型技术路线**: {{ method.typical_pipeline }}

**步骤式流程**:
{% for step in method.pipeline_steps %}
- {{ step }}
{% endfor %}

**证据强度**: {{ method.evidence_strength | default('Emerging') }}

**适用领域**: {{ method.data_domains | join(", ") }}

**适用场景**: {{ method.applicable_scenarios }}

**代表论文**: {{ method.representative_paper_refs | join("; ") if method.representative_paper_refs else "MATERIAL GAP" }}

**优势**:
{% for item in method.strengths %}
- {{ item }}
{% endfor %}

**局限**:
{% for item in method.limitations %}
- {{ item }}
{% endfor %}
{% endfor %}

## 5. 代表论文总结

{% for item in report.paper_summaries %}
### {{ item.display_title or item.title }}

**任务定义**: {{ item.task_definition or item.task }}

**方法**: {{ item.method or "未识别" }}

{{ item.summary }}

**可复现性评估**: {{ item.reproducibility }}

**结果/证据信号**: {{ item.results_signal }}

{% if item.limitations %}

局限与证据说明：{{ item.limitations | join("; ") }}
{% endif %}
{% endfor %}

## 6. 方法比较表

| 方法类别 | 代表论文 | 输入 | 输出 | 算法模式 | 常用指标 | 适用场景 | 局限 |
|---|---|---|---|---|---|---|---|
{% for row in report.method_comparison %}
| {{ row.method_category }} | {{ row.representative_paper_refs | join("; ") if row.representative_paper_refs else "MATERIAL GAP" }} | {{ row.input }} | {{ row.output }} | {{ row.algorithm_pattern }} | {{ row.typical_metrics }} | {{ row.best_for }} | {{ row.limitations }} |
{% endfor %}

## 7. 发展趋势与开放问题

### 方法演进
{% for item in report.research_trends %}
- {{ item }}
{% endfor %}

### 争议与限制性解释
{% for item in report.synthesis.contradictions %}
- {{ item }}
{% endfor %}

### 证据映射（Claim -> 论文）
{% for claim in report.evidence_map %}
- **{{ claim.claim_id }}（{{ claim.strength }}）**: {{ claim.claim }}；引用: {{ claim.citation_refs | join(", ") }}；证据基础: {{ claim.evidence_basis }}
{% endfor %}

## 8. 核心论文表

| # | 年份 | 论文 | 层级 | 作者 | 来源 | 引用 | 代码 | PDF |
|---:|---:|---|---|---|---|---:|---|---|
{% for paper in report.papers %}
| {{ paper.index }} | {{ paper.year }} | {{ paper.display_title | replace("|", "\\|") }} | {{ paper.report_role }} | {{ paper.author_text | replace("|", "\\|") }} | {{ paper.venue | replace("|", "\\|") }} | {{ paper.citation_count }} | {% if paper.code_url %}[Code]({{ paper.code_url }}){% else %}No{% endif %} | {% if paper.pdf_url %}[PDF]({{ paper.pdf_url }}){% else %}No{% endif %} |
{% endfor %}

## 9. 方法分类与证据矩阵

| 论文 | 年份 | 方法类别 | 任务 | 代码 | 证据基础 | 局限 |
|---|---:|---|---|---|---|---|
{% for row in report.literature_matrix %}
| {{ row.display_title | replace("|", "\\|") }} | {{ row.year }} | {{ row.method_category }} | {{ row.task }} | {% if row.code_url %}[Code]({{ row.code_url }}){% else %}No{% endif %} | {{ row.evidence_basis }} | {{ row.limitations | join("; ") }} |
{% endfor %}

## 10. 代码复现状态

| 论文 | 代码链接 | 置信度 |
|---|---|---:|
{% for paper in report.papers %}
| {{ paper.display_title | replace("|", "\\|") }} | {% if paper.code_url %}[Code]({{ paper.code_url }}){% else %}未找到公开仓库{% endif %} | {{ "%.2f"|format(paper.code_confidence) }} |
{% endfor %}

## 11. PDF 与全文状态

已下载 {{ report.pdf_summary.downloaded }} 篇，跳过 {{ report.pdf_summary.skipped }} 篇，失败 {{ report.pdf_summary.failed }} 篇。

| 论文 | 状态 | 原因/路径 |
|---|---|---|
{% for item in report.pdf_summary["items"][:30] %}
| {{ item.display_title | replace("|", "\\|") }} | {{ item.status }} | {{ item.path or item.reason or item.url }} |
{% endfor %}

## 12. 研究空白与后续关键词

### 研究空白
{% for item in report.synthesis.knowledge_gaps %}
- {{ item }}
{% endfor %}

### 后续关键词
{% for item in report.synthesis.follow_up_keywords %}
- {{ item }}
{% endfor %}

## 13. 证据账本与复核 Agent

证据账本记录 {{ report.evidence_ledger.claim_count or 0 }} 条 claim。复核结论：{{ report.review_agents.verdict or "not_run" }}。

| Agent | 严重度 | 问题数 |
|---|---|---:|
{% for agent in report.review_agents.agents or [] %}
| {{ agent.agent }} | {{ agent.severity }} | {{ agent.issues | length }} |
{% endfor %}

## 14. 局限性

{% for item in report.limitations %}
- {{ item }}
{% endfor %}

## 15. 参考文献

{% for paper in report.papers %}
- {{ paper.citation_label }} {{ paper.author_text }} ({{ paper.year }}). *{{ paper.title }}*. {{ paper.venue }}. {% if paper.reference_link_markdown %}{{ paper.reference_link_markdown }}{% else %}无 DOI/URL{% endif %}. 代码：{% if paper.code_url %}[Repository]({{ paper.code_url }}){% else %}未找到公开仓库{% endif %}.
{% endfor %}

## AI Disclosure

{{ report.ai_disclosure }}
"""


EN_TEMPLATE = r"""# {{ report.title }}

**Date**: {{ report.report_date }}  
**Mode**: {{ report.mode }}  
**Quality Gate Verdict**: {{ report.quality_gate.verdict }}

## Abstract

{{ report.abstract.en }}

**Keywords**: {{ report.query.search_queries[:6] | join(", ") }}

## 1. Query Interpretation and Protocol

Original request: `{{ report.query.original }}`  
Recommended query: `{{ report.query.recommended }}`

Research question: {{ report.protocol.research_question }}

### Inclusion Criteria
{% for item in report.protocol.inclusion_criteria %}
- {{ item }}
{% endfor %}

### Exclusion Criteria
{% for item in report.protocol.exclusion_criteria %}
- {{ item }}
{% endfor %}

## 2. Search and Screening Method

| Stage | Count |
|---|---:|
| Initial candidate records | {{ report.prisma.identified }} |
| Records after deduplication | {{ report.prisma.after_dedup }} |
| Core papers | {{ report.prisma.core }} |
| Adjacent papers | {{ report.prisma.adjacent }} |
| Excluded records | {{ report.prisma.excluded }} |
| Reported papers | {{ report.prisma.reported }} |

Sources searched: {{ report.protocol.search_sources | join(", ") }}. Open PDFs were downloaded only when clearly available; no paywall bypassing was attempted.

### Report Size Policy

By default, the formal report does not enforce a minimum paper count. PaperPilot selects core papers first and then includes adjacent papers up to the user-configured maximum. If `--min-report-papers` is explicitly set, related papers may be used to satisfy that requested minimum and are labeled accordingly.

| Metric | Count |
|---|---:|
| Reported papers | {{ report.minimum_report_policy.final_report_count }} |
| User minimum | {{ report.minimum_report_policy.min_report_papers }} |
| Core report papers | {{ report.minimum_report_policy.core_report_count }} |
| Adjacent fill papers | {{ report.minimum_report_policy.adjacent_report_count }} |
| Code-filter fallback | {{ report.minimum_report_policy.code_filter_fallback_count }} |
| Minimum-fill papers | {{ report.minimum_report_policy.minimum_fill_count }} |

### Source Coverage

| Source | Domain | Status | Queries | Returned | Errors |
|---|---|---|---:|---:|---:|
{% for source in report.source_coverage %}
| {{ source.display_name }} | {{ source.domain }} | {{ source.status }} | {{ source.queries }} | {{ source.returned }} | {{ source.errors }} |
{% endfor %}

## 3. Research Background and Problem Definition

{{ report.field_overview.background }}

{{ report.field_overview.problem_definition }}

{{ report.field_overview.why_it_matters }}

### Research Questions (RQ)
{% for item in report.field_overview.research_questions %}
- {{ item }}
{% endfor %}

### Evidence Scope
**Evidence Scope Note**: {{ report.field_overview.scope_note }}
**Applicable Domains**: {{ report.field_overview.applicable_domains | join(", ") }}

## 4. Main Method Families

{% for method in report.method_taxonomy %}
### {{ loop.index }}. {{ method.name }}

**Core idea**: {{ method.core_idea }}

**Typical pipeline**: {{ method.typical_pipeline }}

**Pipeline steps**:
{% for step in method.pipeline_steps %}
- {{ step }}
{% endfor %}

**Evidence strength**: {{ method.evidence_strength | default('Emerging') }}

**Data domains**: {{ method.data_domains | join(", ") }}

**Applicable scenario**: {{ method.applicable_scenarios }}

**Representative papers**: {{ method.representative_paper_refs | join("; ") if method.representative_paper_refs else "MATERIAL GAP" }}

**Strengths**:
{% for item in method.strengths %}
- {{ item }}
{% endfor %}

**Limitations**:
{% for item in method.limitations %}
- {{ item }}
{% endfor %}
{% endfor %}

## 5. Representative Paper Summaries

{% for item in report.paper_summaries %}
### {{ item.display_title or item.title }}

**Task definition**: {{ item.task_definition or item.task }}

**Method**: {{ item.method or "unknown" }}

{{ item.summary }}

**Reproducibility**: {{ item.reproducibility }}

**Evidence signal**: {{ item.results_signal }}

{% if item.limitations %}

Evidence limitations: {{ item.limitations | join("; ") }}
{% endif %}
{% endfor %}

## 6. Method Comparison

| Method Category | Representative Papers | Input | Output | Algorithm Pattern | Typical Metrics | Best For | Limitations |
|---|---|---|---|---|---|---|---|
{% for row in report.method_comparison %}
| {{ row.method_category }} | {{ row.representative_paper_refs | join("; ") if row.representative_paper_refs else "MATERIAL GAP" }} | {{ row.input }} | {{ row.output }} | {{ row.algorithm_pattern }} | {{ row.typical_metrics }} | {{ row.best_for }} | {{ row.limitations }} |
{% endfor %}

## 7. Research Trends and Open Questions

### Method Evolution
{% for item in report.research_trends %}
- {{ item }}
{% endfor %}

### Contradictions and Cautions
{% for item in report.synthesis.contradictions %}
- {{ item }}
{% endfor %}

### Evidence Map (Claim -> Papers)
{% for claim in report.evidence_map %}
- **{{ claim.claim_id }} ({{ claim.strength }})**: {{ claim.claim }}; refs: {{ claim.citation_refs | join(", ") }}; basis: {{ claim.evidence_basis }}
{% endfor %}

## 8. Core Papers

| # | Year | Paper | Tier | Authors | Venue | Cites | Code | PDF |
|---:|---:|---|---|---|---|---:|---|---|
{% for paper in report.papers %}
| {{ paper.index }} | {{ paper.year }} | {{ paper.display_title | replace("|", "\\|") }} | {{ paper.report_role }} | {{ paper.author_text | replace("|", "\\|") }} | {{ paper.venue | replace("|", "\\|") }} | {{ paper.citation_count }} | {% if paper.code_url %}[Code]({{ paper.code_url }}){% else %}No{% endif %} | {% if paper.pdf_url %}[PDF]({{ paper.pdf_url }}){% else %}No{% endif %} |
{% endfor %}

## 9. Evidence Matrix

| Paper | Year | Method Category | Task | Code | Evidence Basis | Limitations |
|---|---:|---|---|---|---|---|
{% for row in report.literature_matrix %}
| {{ row.display_title | replace("|", "\\|") }} | {{ row.year }} | {{ row.method_category }} | {{ row.task }} | {% if row.code_url %}[Code]({{ row.code_url }}){% else %}No{% endif %} | {{ row.evidence_basis }} | {{ row.limitations | join("; ") }} |
{% endfor %}

## 10. Code Reproducibility

| Paper | Code URL | Confidence |
|---|---|---:|
{% for paper in report.papers %}
| {{ paper.display_title | replace("|", "\\|") }} | {% if paper.code_url %}[Code]({{ paper.code_url }}){% else %}No public code found{% endif %} | {{ "%.2f"|format(paper.code_confidence) }} |
{% endfor %}

## 11. PDF and Full-Text Status

Downloaded {{ report.pdf_summary.downloaded }} PDFs, skipped {{ report.pdf_summary.skipped }}, failed {{ report.pdf_summary.failed }}.

| Paper | Status | Reason/Path |
|---|---|---|
{% for item in report.pdf_summary["items"][:30] %}
| {{ item.display_title | replace("|", "\\|") }} | {{ item.status }} | {{ item.path or item.reason or item.url }} |
{% endfor %}

## 12. Research Gaps and Follow-up Keywords

### Research Gaps
{% for item in report.synthesis.knowledge_gaps %}
- {{ item }}
{% endfor %}

### Follow-up Keywords
{% for item in report.synthesis.follow_up_keywords %}
- {{ item }}
{% endfor %}

## 13. Evidence Ledger and Review Agents

The evidence ledger records {{ report.evidence_ledger.claim_count or 0 }} claims. Review verdict: {{ report.review_agents.verdict or "not_run" }}.

| Agent | Severity | Issue Count |
|---|---|---:|
{% for agent in report.review_agents.agents or [] %}
| {{ agent.agent }} | {{ agent.severity }} | {{ agent.issues | length }} |
{% endfor %}

## 14. Limitations

{% for item in report.limitations %}
- {{ item }}
{% endfor %}

## 15. References

{% for paper in report.papers %}
- {{ paper.citation_label }} {{ paper.author_text }} ({{ paper.year }}). *{{ paper.title }}*. {{ paper.venue }}. {% if paper.reference_link_markdown %}{{ paper.reference_link_markdown }}{% else %}No DOI/URL{% endif %}. Code: {% if paper.code_url %}[Repository]({{ paper.code_url }}){% else %}not found{% endif %}.
{% endfor %}

## AI Disclosure

{{ report.ai_disclosure }}
"""
