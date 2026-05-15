from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__


def write_obsidian_wiki(
    canonical: dict[str, Any],
    output_dir: Path,
    *,
    task_id: str,
) -> dict[str, Any]:
    vault = output_dir / "obsidian_wiki"
    for folder in ["papers", "methods", "topics", "claims", "_meta", "reports"]:
        (vault / folder).mkdir(parents=True, exist_ok=True)

    page_map: dict[str, str] = {}
    written: list[str] = []

    index_path = vault / "index.md"
    index_path.write_text(_index_note(canonical, task_id), encoding="utf-8")
    written.append(str(index_path.relative_to(vault)))
    page_map["index"] = "index"

    for paper in canonical.get("papers", []):
        page_name = _paper_page_name(paper)
        page_map[f"paper:{paper.get('citation_key')}"] = page_name
        path = vault / "papers" / f"{page_name}.md"
        path.write_text(_paper_note(canonical, paper, task_id), encoding="utf-8")
        written.append(str(path.relative_to(vault)))

    for method in canonical.get("method_taxonomy", []):
        page_name = _safe_page_name(str(method.get("name") or "Method"))
        page_map[f"method:{method.get('name')}"] = page_name
        path = vault / "methods" / f"{page_name}.md"
        path.write_text(_method_note(method, task_id), encoding="utf-8")
        written.append(str(path.relative_to(vault)))

    for topic in _topics(canonical):
        page_name = _safe_page_name(topic)
        page_map[f"topic:{topic}"] = page_name
        path = vault / "topics" / f"{page_name}.md"
        path.write_text(_topic_note(topic, canonical, task_id), encoding="utf-8")
        written.append(str(path.relative_to(vault)))

    for claim in canonical.get("evidence_map", []):
        page_name = _safe_page_name(str(claim.get("claim_id") or claim.get("claim") or "claim"))
        page_map[f"claim:{claim.get('claim_id')}"] = page_name
        path = vault / "claims" / f"{page_name}.md"
        path.write_text(_claim_note(claim, task_id), encoding="utf-8")
        written.append(str(path.relative_to(vault)))

    for filename in ["report.zh.md", "report.en.md"]:
        source = output_dir / filename
        if source.exists():
            target = vault / "reports" / filename
            shutil.copyfile(source, target)
            written.append(str(target.relative_to(vault)))

    taxonomy_path = vault / "_meta" / "taxonomy.md"
    taxonomy_path.write_text(_taxonomy_note(canonical, task_id), encoding="utf-8")
    written.append(str(taxonomy_path.relative_to(vault)))

    lint = _lint_vault(vault)
    lint_path = vault / "_meta" / "wiki_lint.json"
    lint_path.write_text(json.dumps(lint, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(str(lint_path.relative_to(vault)))

    manifest = {
        "task_id": task_id,
        "paperpilot_version": __version__,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "vault_path": str(vault.resolve()),
        "source_files": _source_files(output_dir),
        "pages": [{"path": path, "content_hash": _sha256(vault / path)} for path in sorted(written)],
        "page_count": len(written),
        "paper_count": len(canonical.get("papers", [])),
        "method_count": len(canonical.get("method_taxonomy", [])),
        "claim_count": len(canonical.get("evidence_map", [])),
        "lint": lint,
    }
    manifest_path = vault / "_meta" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _index_note(canonical: dict[str, Any], task_id: str) -> str:
    papers = canonical.get("papers", [])
    methods = canonical.get("method_taxonomy", [])
    topics = _topics(canonical)
    return "\n".join(
        [
            _frontmatter(
                {
                    "title": canonical.get("title", "PaperPilot Literature Wiki"),
                    "type": "index",
                    "summary": f"Obsidian wiki generated from PaperPilot task {task_id}.",
                    "task_id": task_id,
                    "tags": ["paperpilot", "literature-review", "wiki"],
                    "provenance": "generated",
                    "source_files": ["report.canonical.json"],
                }
            ),
            f"# {canonical.get('title', 'PaperPilot Literature Wiki')}",
            "",
            f"Task: `{task_id}`",
            f"Report date: `{canonical.get('report_date', '')}`",
            f"Reported papers: **{len(papers)}**",
            "",
            "## Research Questions",
            *[f"- {item}" for item in canonical.get("research_questions", [])],
            "",
            "## Core Entry Points",
            "- [[reports/report.zh|Chinese report]]",
            "- [[reports/report.en|English report]]",
            "- [[_meta/taxonomy|Tag taxonomy]]",
            "",
            "## Papers",
            *[f"- [[papers/{_paper_page_name(paper)}|{paper.get('citation_label')} {paper.get('title')}]]" for paper in papers],
            "",
            "## Method Families",
            *[f"- [[methods/{_safe_page_name(str(method.get('name') or 'Method'))}|{method.get('name')}]]" for method in methods],
            "",
            "## Topics",
            *[f"- [[topics/{_safe_page_name(topic)}|{topic}]]" for topic in topics],
            "",
        ]
    )


def _paper_note(canonical: dict[str, Any], paper: dict[str, Any], task_id: str) -> str:
    summary = _summary_for_paper(canonical, paper)
    method = paper.get("method_category") or (summary or {}).get("method") or "Unknown"
    method_page = _safe_page_name(str(method))
    role = paper.get("report_role") or (paper.get("raw") or {}).get("report_role") or "core"
    return "\n".join(
        [
            _frontmatter(
                {
                    "title": paper.get("title"),
                    "type": "paper",
                    "summary": (summary or {}).get("summary") or paper.get("inclusion_reason") or "Paper note generated from PaperPilot metadata.",
                    "task_id": task_id,
                    "citation_key": paper.get("citation_key"),
                    "tags": ["paper", "paperpilot", f"role/{role}", f"method/{_tag_slug(method)}"],
                    "provenance": "metadata_or_abstract",
                    "source_files": ["report.canonical.json", "ranked_papers.json"],
                }
            ),
            f"# {paper.get('citation_label')} {paper.get('title')}",
            "",
            f"- Year: {paper.get('year')}",
            f"- Authors: {paper.get('author_text')}",
            f"- Venue: {paper.get('venue') or 'Unknown'}",
            f"- Method family: [[methods/{method_page}|{method}]]",
            f"- Report role: `{role}`",
            f"- Evidence basis: `{_matrix_value(canonical, paper, 'evidence_basis') or 'metadata_or_abstract_only'}`",
            f"- Paper URL: {paper.get('reference_link') or paper.get('url') or 'not available'}",
            f"- PDF: {paper.get('pdf_url') or 'not available'}",
            f"- Code: {paper.get('code_url') or 'not found'}",
            "",
            "## Summary",
            (summary or {}).get("summary") or paper.get("inclusion_reason") or "No detailed summary available.",
            "",
            "## Task and Method",
            f"- Task: {(summary or {}).get('task_definition') or _matrix_value(canonical, paper, 'task') or 'Unknown'}",
            f"- Method: {(summary or {}).get('method') or method}",
            f"- Reproducibility: {(summary or {}).get('reproducibility') or 'Not assessed'}",
            f"- Results signal: {(summary or {}).get('results_signal') or 'MATERIAL GAP'}",
            "",
            "## Related Claims",
            *_claim_links(canonical, paper),
            "",
            "## Related Topics",
            *_topic_links(canonical),
            "",
        ]
    )


def _method_note(method: dict[str, Any], task_id: str) -> str:
    title = str(method.get("name") or "Method")
    refs = method.get("representative_paper_refs") or []
    return "\n".join(
        [
            _frontmatter(
                {
                    "title": title,
                    "type": "method",
                    "summary": method.get("core_idea") or "Method-family note generated from PaperPilot synthesis.",
                    "task_id": task_id,
                    "tags": ["method", "paperpilot", f"method/{_tag_slug(title)}"],
                    "provenance": "inferred",
                    "source_files": ["synthesis.json", "report.canonical.json"],
                }
            ),
            f"# {title}",
            "",
            "## Core Idea",
            str(method.get("core_idea") or "MATERIAL GAP"),
            "",
            "## Pipeline",
            *[f"- {step}" for step in method.get("pipeline_steps") or []],
            "",
            "## Strengths",
            *[f"- {item}" for item in method.get("strengths") or []],
            "",
            "## Limitations",
            *[f"- {item}" for item in method.get("limitations") or []],
            "",
            "## Representative Papers",
            *[f"- {ref}" for ref in refs],
            "",
        ]
    )


def _topic_note(topic: str, canonical: dict[str, Any], task_id: str) -> str:
    return "\n".join(
        [
            _frontmatter(
                {
                    "title": topic,
                    "type": "topic",
                    "summary": f"Topic page for {topic}.",
                    "task_id": task_id,
                    "tags": ["topic", "paperpilot", f"topic/{_tag_slug(topic)}"],
                    "provenance": "generated",
                    "source_files": ["plan.json", "protocol.json", "report.canonical.json"],
                }
            ),
            f"# {topic}",
            "",
            "## Related Search Queries",
            *[f"- {query}" for query in canonical.get("query", {}).get("search_queries", []) if topic.lower() in query.lower()],
            "",
            "## Related Papers",
            *[f"- [[papers/{_paper_page_name(paper)}|{paper.get('citation_label')} {paper.get('title')}]]" for paper in canonical.get("papers", [])],
            "",
        ]
    )


def _claim_note(claim: dict[str, Any], task_id: str) -> str:
    title = str(claim.get("claim_id") or "claim")
    return "\n".join(
        [
            _frontmatter(
                {
                    "title": title,
                    "type": "claim",
                    "summary": str(claim.get("claim") or "")[:220],
                    "task_id": task_id,
                    "tags": ["claim", "paperpilot", f"evidence/{_tag_slug(str(claim.get('strength') or 'emerging'))}"],
                    "provenance": "inferred",
                    "source_files": ["evidence_ledger.json", "report.canonical.json"],
                }
            ),
            f"# {title}",
            "",
            str(claim.get("claim") or "MATERIAL GAP"),
            "",
            f"Evidence strength: `{claim.get('strength') or 'Emerging'}`",
            f"Evidence basis: `{claim.get('evidence_basis') or 'metadata_or_abstract_only'}`",
            "",
            "## Citation References",
            *[f"- {ref}" for ref in claim.get("citation_refs") or []],
            "",
        ]
    )


def _taxonomy_note(canonical: dict[str, Any], task_id: str) -> str:
    tags = sorted(
        {
            "paperpilot",
            "literature-review",
            "paper",
            "method",
            "topic",
            "claim",
            *[f"method/{_tag_slug(str(method.get('name') or 'method'))}" for method in canonical.get("method_taxonomy", [])],
            *[f"topic/{_tag_slug(topic)}" for topic in _topics(canonical)],
        }
    )
    return "\n".join(
        [
            _frontmatter(
                {
                    "title": "PaperPilot Wiki Taxonomy",
                    "type": "taxonomy",
                    "summary": "Controlled tags generated for this PaperPilot Obsidian wiki.",
                    "task_id": task_id,
                    "tags": ["paperpilot", "taxonomy"],
                    "provenance": "generated",
                    "source_files": ["report.canonical.json"],
                }
            ),
            "# PaperPilot Wiki Taxonomy",
            "",
            *[f"- `#{tag}`" for tag in tags],
            "",
        ]
    )


def _frontmatter(values: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in values.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def _yaml_scalar(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").strip()
    return json.dumps(text, ensure_ascii=False)


def _paper_page_name(paper: dict[str, Any]) -> str:
    return _safe_page_name(f"{paper.get('index', '')} {paper.get('title', 'paper')}")


def _safe_page_name(value: str) -> str:
    text = re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", value)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        text = "untitled"
    return text[:96].strip()


def _tag_slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "-", value.strip().lower())
    return text.strip("-") or "unknown"


def _summary_for_paper(canonical: dict[str, Any], paper: dict[str, Any]) -> dict[str, Any] | None:
    key = paper.get("citation_key")
    for summary in canonical.get("paper_summaries", []):
        if summary.get("citation_key") == key:
            return summary
    return None


def _matrix_value(canonical: dict[str, Any], paper: dict[str, Any], key: str) -> Any:
    citation_key = paper.get("citation_key")
    for row in canonical.get("literature_matrix", []):
        if row.get("citation_key") == citation_key:
            return row.get(key)
    return None


def _claim_links(canonical: dict[str, Any], paper: dict[str, Any]) -> list[str]:
    label = paper.get("citation_label")
    links = []
    for claim in canonical.get("evidence_map", []):
        refs = claim.get("citation_refs") or []
        if label and any(str(ref).startswith(label) for ref in refs):
            page = _safe_page_name(str(claim.get("claim_id") or claim.get("claim") or "claim"))
            links.append(f"- [[claims/{page}|{claim.get('claim_id') or 'claim'}]]")
    return links or ["- MATERIAL GAP"]


def _topic_links(canonical: dict[str, Any]) -> list[str]:
    return [f"- [[topics/{_safe_page_name(topic)}|{topic}]]" for topic in _topics(canonical)[:8]]


def _topics(canonical: dict[str, Any]) -> list[str]:
    values = []
    query = canonical.get("query", {})
    values.extend(query.get("interpretations") or [])
    values.extend(query.get("search_queries") or [])
    for method in canonical.get("method_taxonomy", []):
        if method.get("name"):
            values.append(str(method["name"]))
    topics: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", str(value)).strip()
        if cleaned and cleaned not in topics:
            topics.append(cleaned[:80])
    return topics[:18]


def _source_files(output_dir: Path) -> list[str]:
    names = [
        "report.canonical.json",
        "ranked_papers.json",
        "synthesis.json",
        "literature_matrix.json",
        "evidence_ledger.json",
        "quality_gate.json",
        "source_diagnostics.json",
    ]
    return [name for name in names if (output_dir / name).exists()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lint_vault(vault: Path) -> dict[str, Any]:
    pages = {path.stem: path for path in vault.rglob("*.md")}
    pages.update({str(path.relative_to(vault).with_suffix("")): path for path in vault.rglob("*.md")})
    broken: list[dict[str, str]] = []
    missing_frontmatter: list[str] = []
    linked_targets: set[str] = set()
    for path in vault.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(vault))
        if not text.startswith("---\n"):
            missing_frontmatter.append(rel)
        for target in re.findall(r"\[\[([^|\]]+)(?:\|[^\]]+)?\]\]", text):
            normalized = target.strip().removesuffix(".md")
            linked_targets.add(normalized)
            if normalized not in pages:
                broken.append({"source": rel, "target": normalized})
    orphan_pages = sorted(
        str(path.relative_to(vault))
        for key, path in pages.items()
        if "/" in key and key not in linked_targets and not key.startswith("_meta/") and path.name != "index.md"
    )
    return {
        "broken_wikilinks": broken,
        "missing_frontmatter": sorted(set(missing_frontmatter)),
        "orphan_pages": orphan_pages,
        "broken_wikilink_count": len(broken),
        "missing_frontmatter_count": len(set(missing_frontmatter)),
        "orphan_page_count": len(orphan_pages),
    }
