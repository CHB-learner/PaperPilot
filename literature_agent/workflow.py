from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import load_app_config
from .corpus import corpus_items_from_papers, enhanced_deduplicate, split_corpus
from .events import EventLogger, read_events
from .evidence import build_evidence_ledger
from .pdf import attach_fulltext_paths, download_pdfs, enrich_unpaywall, extract_downloaded_fulltext
from .pdf_report import write_pdf_report
from .planner import make_plan
from .processing import apply_github_filter, enrich_github_links, rank_papers, resolve_code_links
from .prompts import prompt_manifest
from .protocol import build_protocol
from .query import understand_query
from .reflection import reflect
from .registries import registry_manifest
from .report import build_canonical_report, render_html_reports, render_reports
from .review_agents import run_review_agents
from .searchers import search_all as _legacy_search_all
from .searchers import search_all_with_diagnostics
from .synthesis import build_literature_matrix, build_synthesis
from .ui import console, print_success, stage_done, stage_start
from .user_corpus import load_user_corpus
from .utils import create_task_dir, write_json
from .verification import build_quality_gate, verify_corpus, verification_to_dict


STAGES = [
    "intake",
    "protocol",
    "search",
    "corpus",
    "screening",
    "verification",
    "synthesis",
    "review",
    "report",
]


search_all = _legacy_search_all


def run_v1_workflow(args: argparse.Namespace, client) -> int:
    output_dir, task_id = prepare_output_dir(args)
    events = EventLogger(output_dir)
    app_config = load_app_config()
    state = init_state(task_id, args, output_dir, client)
    write_state(output_dir, state)
    write_json(output_dir / "task.json", task_payload(task_id, args, output_dir))
    write_json(output_dir / "prompt_manifest.json", prompt_manifest())
    write_json(output_dir / "registries.json", registry_manifest(app_config.sources))
    events.emit("start", "intake", "Run created", task_id=task_id, model=getattr(client, "model", None))
    console.rule("[bold cyan]PaperPilot Run")
    console.print(f"[bold]Task ID:[/bold] [cyan]{task_id}[/cyan]")
    console.print(f"[bold]Output:[/bold] [cyan]{output_dir.resolve()}[/cyan]\n")

    mark_stage(output_dir, state, "intake", "running", events=events)
    stage_start(1, 9, "Intake", f"Understanding query: {args.keyword}")
    understanding = understand_query(args.keyword, client)
    (output_dir / "query_understanding.md").write_text(understanding.to_markdown(), encoding="utf-8")
    if understanding.needs_confirmation and not args.auto_confirm and getattr(args, "interaction", "auto") != "auto":
        answer = input("Keyword is broad or ambiguous. Continue with the recommended query? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            mark_stage(output_dir, state, "intake", "needs_user_attention", events=events)
            print("Stopped before search. Review query_understanding.md and rerun with a more specific keyword.")
            return 2
    mark_stage(output_dir, state, "intake", "completed", events=events)
    stage_done("Intake", {"query": understanding.recommended_query})

    mark_stage(output_dir, state, "protocol", "running", events=events)
    stage_start(2, 9, "Protocol", "Creating search plan and research protocol")
    plan = make_plan(understanding, args.max_papers, args.since_year, client, seed_search_terms=getattr(args, "seed_search_terms", None))
    protocol = build_protocol(understanding, plan, args.github_filter, client)
    write_json(output_dir / "plan.json", plan.to_dict())
    write_json(output_dir / "protocol.json", protocol.to_dict())
    mark_stage(output_dir, state, "protocol", "completed", events=events)
    stage_done("Protocol", {"queries": len(plan.search_queries), "sources": len(protocol.search_sources)})

    mark_stage(output_dir, state, "search", "running", events=events)
    stage_start(3, 9, "Search", "Querying source registry and optional user corpus")
    user_papers, user_corpus_log = load_user_corpus(getattr(args, "user_corpus", None))
    write_json(output_dir / "user_corpus_log.json", user_corpus_log)
    if user_papers:
        events.emit("progress", "search", "Loaded user corpus", count=len(user_papers))
    per_query_limit = candidate_limit(args.max_papers, len(plan.search_queries), args.github_filter)
    if search_all is not _legacy_search_all:
        searched_papers = search_all(plan, per_query_limit=per_query_limit)
        source_diagnostics = {"enabled_sources": ["test"], "total_returned": len(searched_papers), "sources": {}}
    else:
        searched_papers, source_diagnostics = search_all_with_diagnostics(
            plan,
            per_query_limit=per_query_limit,
            source_mode=getattr(args, "sources", "auto"),
            source_configs=app_config.sources,
            enable_sources=getattr(args, "enable_source", None) or [],
            disable_sources=getattr(args, "disable_source", None) or [],
        )
    raw_papers = user_papers + searched_papers
    write_json(output_dir / "source_diagnostics.json", source_diagnostics)
    write_json(output_dir / "metadata.json", [paper.to_dict() for paper in raw_papers])
    mark_stage(
        output_dir,
        state,
        "search",
        "completed",
        {"raw_count": len(raw_papers), "user_corpus": len(user_papers), "sources": source_diagnostics.get("enabled_sources", [])},
        events=events,
    )
    stage_done(
        "Search",
        {
            "sources": len(source_diagnostics.get("enabled_sources", [])),
            "candidates": len(raw_papers),
            "failures": count_source_failures(source_diagnostics),
        },
    )

    mark_stage(output_dir, state, "corpus", "running", events=events)
    stage_start(4, 9, "Corpus", "Normalizing, deduplicating, ranking, and resolving code links")
    resolved = resolve_code_links(raw_papers)
    deduped, dedup_stats = enhanced_deduplicate(resolved)
    rank_papers(deduped, plan.recommended_query, args.since_year)
    github_enrichment = {"checked": 0, "enriched": 0, "skipped_existing_code": 0}
    if args.github_search_limit and args.github_filter in {"required", "any"}:
        console.print("[dim]Searching GitHub for missing code links...[/dim]")
        github_enrichment = enrich_github_links(deduped, max_checks=args.github_search_limit)
        rank_papers(deduped, plan.recommended_query, args.since_year)
    mark_stage(output_dir, state, "corpus", "completed", {"dedup": dedup_stats, "github_enrichment": github_enrichment}, events=events)
    stage_done(
        "Corpus",
        {
            "raw": len(raw_papers),
            "deduped": len(deduped),
            "github+": github_enrichment.get("enriched", 0),
        },
    )

    mark_stage(output_dir, state, "screening", "running", events=events)
    stage_start(5, 9, "Screening", "Classifying papers as core, adjacent, or excluded")
    items = corpus_items_from_papers(deduped, plan, protocol, client)
    core_items, adjacent_items, excluded_items = split_corpus(items)
    final_core_items = final_view(core_items, args.github_filter, args.max_papers)
    if not final_core_items and core_items:
        final_core_items = core_items[: args.max_papers]
    write_json(output_dir / "corpus.json", [item.to_dict() for item in items])
    write_json(output_dir / "core_papers.json", [item.to_dict() for item in core_items])
    write_json(output_dir / "adjacent_papers.json", [item.to_dict() for item in adjacent_items])
    write_json(output_dir / "excluded_papers.json", [item.to_dict() for item in excluded_items])
    mark_stage(
        output_dir,
        state,
        "screening",
        "completed",
        {"core": len(core_items), "adjacent": len(adjacent_items), "excluded": len(excluded_items), "final": len(final_core_items)},
        events=events,
    )
    stage_done(
        "Screening",
        {"core": len(core_items), "adjacent": len(adjacent_items), "excluded": len(excluded_items), "final": len(final_core_items)},
    )

    mark_stage(output_dir, state, "verification", "running", events=events)
    stage_start(6, 9, "Verification", "Checking links and downloading open PDFs")
    final_papers = [item.paper for item in final_core_items]
    enrich_unpaywall(final_papers, args.unpaywall_email)
    if args.no_download:
        download_log = [{"title": paper.title, "status": "skipped", "reason": "--no-download"} for paper in final_papers]
    else:
        download_log = download_pdfs(final_papers, output_dir / "pdfs", limit=args.pdf_limit)
    write_json(output_dir / "download_log.json", download_log)
    paper_notes = extract_downloaded_fulltext(download_log, output_dir)
    attach_fulltext_paths(final_papers, paper_notes)
    write_json(output_dir / "ranked_papers.json", [item.paper.to_dict() for item in final_core_items])
    verification = verify_corpus(items, download_log)
    write_json(output_dir / "verification.json", verification_to_dict(verification))
    mark_stage(output_dir, state, "verification", "completed", events=events)
    stage_done("Verification", download_status_counts(download_log))

    mark_stage(output_dir, state, "synthesis", "running", events=events)
    stage_start(7, 9, "Synthesis", "Building literature matrix and field-level synthesis")
    matrix_items = core_items + (adjacent_items if args.include_adjacent else [])
    literature_matrix = build_literature_matrix(matrix_items)
    synthesis = build_synthesis(core_items, adjacent_items, literature_matrix, plan, protocol, client)
    write_json(output_dir / "literature_matrix.json", literature_matrix)
    write_json(output_dir / "synthesis.json", synthesis)
    mark_stage(output_dir, state, "synthesis", "completed", events=events)
    stage_done("Synthesis", {"matrix_rows": len(literature_matrix), "method_families": len(synthesis.get("method_taxonomy") or [])})

    mark_stage(output_dir, state, "review", "running", events=events)
    stage_start(8, 9, "Review", "Running quality gate, reflection, and review checks")
    quality_gate = build_quality_gate(
        items,
        final_core_items,
        verification,
        download_log,
        max_papers=args.max_papers,
        github_filter=args.github_filter,
        quality=args.quality,
        dedup_stats=dedup_stats,
    )
    reflection = reflect(final_papers, plan, download_log, args.github_filter, client)
    reflection.update(
        {
            "verdict": quality_gate.verdict,
            "quality_gate_issues": quality_gate.issues,
            "quality_gate_recommendations": quality_gate.recommendations,
            "before_github_filter_count": len(core_items),
            "after_github_filter_count": len(final_core_items),
            "github_enrichment": github_enrichment,
            "task_id": task_id,
            "retry_performed": False,
        }
    )
    write_json(output_dir / "quality_gate.json", quality_gate.to_dict())
    write_json(output_dir / "reflection.json", reflection)
    mark_stage(output_dir, state, "review", "completed", {"verdict": quality_gate.verdict}, events=events)
    stage_done("Review", {"verdict": quality_gate.verdict, "issues": len(quality_gate.issues)})

    mark_stage(output_dir, state, "report", "running", events=events)
    stage_start(9, 9, "Report", "Writing canonical, bilingual Markdown, HTML, and PDF reports")
    canonical = build_canonical_report(
        understanding,
        plan,
        protocol,
        final_core_items,
        core_items,
        adjacent_items,
        excluded_items,
        literature_matrix,
        synthesis,
        verification,
        quality_gate,
        download_log,
        reflection,
        None,
        None,
        source_diagnostics,
        mode=args.mode,
        include_adjacent=args.include_adjacent,
        client=client,
    )
    evidence_ledger = build_evidence_ledger(canonical, literature_matrix)
    review_agent_findings = run_review_agents(core_items, final_core_items, verification, canonical, evidence_ledger)
    write_json(output_dir / "evidence_ledger.json", evidence_ledger)
    write_json(output_dir / "review_agent_findings.json", review_agent_findings)
    canonical["evidence_ledger"] = evidence_ledger
    canonical["review_agents"] = review_agent_findings
    write_json(output_dir / "report.canonical.json", canonical)
    zh, en = render_reports(canonical)
    (output_dir / "report.zh.md").write_text(zh, encoding="utf-8")
    (output_dir / "report.en.md").write_text(en, encoding="utf-8")
    zh_html, en_html = render_html_reports(canonical)
    (output_dir / "report.zh.html").write_text(zh_html, encoding="utf-8")
    (output_dir / "report.en.html").write_text(en_html, encoding="utf-8")
    write_pdf_report(zh, output_dir / "report.zh.pdf", title=canonical["title_zh"])
    write_pdf_report(en, output_dir / "report.en.pdf", title=canonical["title"])
    mark_stage(output_dir, state, "report", "completed", {"review_verdict": review_agent_findings["verdict"]}, events=events)
    stage_done("Report", {"files": "report.zh/en.md/html/pdf", "review": review_agent_findings["verdict"]})
    write_manifest(output_dir, state, client)
    events.emit("done", "report", "Run completed", output_dir=str(output_dir.resolve()))
    print_success(f"Done. Output: {output_dir.resolve()}")
    return 0


def count_source_failures(source_diagnostics: dict[str, Any]) -> int:
    failures = 0
    for info in (source_diagnostics.get("sources") or {}).values():
        if info.get("status") == "error" or info.get("errors"):
            failures += 1
    return failures


def download_status_counts(download_log: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    for item in download_log:
        status = item.get("status") or "failed"
        if status in counts:
            counts[status] += 1
        else:
            counts["failed"] += 1
    return counts


def prepare_output_dir(args: argparse.Namespace) -> tuple[Path, str]:
    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir, output_dir.name
    task_id, output_dir = create_task_dir(args.keyword)
    return output_dir, task_id


def task_payload(task_id: str, args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "keyword": args.keyword,
        "output_dir": str(output_dir.resolve()),
        "max_papers": args.max_papers,
        "since_year": args.since_year,
        "github_filter": args.github_filter,
        "no_download": args.no_download,
        "github_search_limit": args.github_search_limit,
        "mode": getattr(args, "mode", "apa"),
        "interaction": getattr(args, "interaction", "auto"),
        "quality": getattr(args, "quality", "balanced"),
        "include_adjacent": getattr(args, "include_adjacent", False),
        "user_corpus": getattr(args, "user_corpus", None) or [],
        "sources": getattr(args, "sources", "auto"),
        "enable_source": getattr(args, "enable_source", None) or [],
        "disable_source": getattr(args, "disable_source", None) or [],
    }


def init_state(task_id: str, args: argparse.Namespace, output_dir: Path, client) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "keyword": args.keyword,
        "output_dir": str(output_dir.resolve()),
        "model": getattr(client, "model", None),
        "usage": {"tokens": None, "cost": None, "note": "Token and cost tracking are not available for the current OpenAI-compatible client."},
        "stages": {stage: {"status": "pending"} for stage in STAGES},
    }


def mark_stage(
    output_dir: Path,
    state: dict[str, Any],
    stage: str,
    status: str,
    extra: dict[str, Any] | None = None,
    events: EventLogger | None = None,
) -> None:
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    state["stages"].setdefault(stage, {})
    state["stages"][stage].update({"status": status, "updated_at": state["updated_at"]})
    if extra:
        state["stages"][stage].update(extra)
    write_state(output_dir, state)
    if events:
        events.emit("stage", stage, f"{stage} {status}", status=status, **(extra or {}))


def write_state(output_dir: Path, state: dict[str, Any]) -> None:
    write_json(output_dir / "state.json", state)


def write_manifest(output_dir: Path, state: dict[str, Any], client) -> None:
    files = sorted(str(path.relative_to(output_dir)) for path in output_dir.rglob("*") if path.is_file())
    manifest = {
        "task_id": state["task_id"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "paperpilot_version": "1.3.3",
        "model": getattr(client, "model", None),
        "files": files,
    }
    write_json(output_dir / "manifest.json", manifest)


def final_view(core_items, github_filter: str, max_papers: int):
    papers = apply_github_filter([item.paper for item in core_items], github_filter)
    allowed = {id(paper) for paper in papers}
    return [item for item in core_items if id(item.paper) in allowed][:max_papers]


def candidate_limit(max_papers: int, query_count: int, github_filter: str) -> int:
    query_count = max(1, query_count)
    if github_filter == "required":
        return max(12, min(35, (max_papers * 4) // query_count))
    return max(10, min(30, (max_papers * 3) // query_count))


def inspect_run(path_or_id: str) -> int:
    run_dir = resolve_run_dir(path_or_id)
    if not run_dir:
        print(f"Run not found: {path_or_id}")
        return 1
    print(f"Run: {run_dir.resolve()}")
    for filename in ["state.json", "source_diagnostics.json", "quality_gate.json", "review_agent_findings.json", "evidence_ledger.json", "reflection.json", "manifest.json"]:
        path = run_dir / filename
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        print(f"\n== {filename} ==")
        if filename == "state.json":
            for stage, info in data.get("stages", {}).items():
                print(f"{stage}: {info.get('status')}")
            usage = data.get("usage") or {}
            if usage:
                print(f"usage: tokens={usage.get('tokens') or 'not tracked'}, cost={usage.get('cost') or 'not tracked'}")
        elif filename == "quality_gate.json":
            print(f"verdict: {data.get('verdict')}")
            print(f"issues: {', '.join(data.get('issues') or []) or 'none'}")
            print(f"metrics: {json.dumps(data.get('metrics') or {}, ensure_ascii=False)[:1200]}")
        elif filename == "source_diagnostics.json":
            print(f"enabled sources: {', '.join(data.get('enabled_sources') or []) or 'none'}")
            for source, info in (data.get("sources") or {}).items():
                print(f"{source}: {info.get('status')} returned={info.get('returned')} errors={len(info.get('errors') or [])}")
        elif filename == "review_agent_findings.json":
            print(f"verdict: {data.get('verdict')}")
            print(f"blocking issues: {', '.join(data.get('blocking_issues') or []) or 'none'}")
        elif filename == "evidence_ledger.json":
            print(f"claims: {data.get('claim_count', 0)}")
        elif filename == "reflection.json":
            print(f"verdict: {data.get('verdict')}")
            print(f"issues: {', '.join(data.get('issues') or []) or 'none'}")
        else:
            print(f"files: {len(data.get('files') or [])}")
    events = read_events(run_dir / "events.jsonl", limit=8)
    if events:
        print("\n== events.jsonl ==")
        for event in events:
            print(f"{event.get('timestamp')} {event.get('stage')} {event.get('type')}: {event.get('message')}")
    return 0


def resolve_run_dir(path_or_id: str) -> Path | None:
    candidate = Path(path_or_id).expanduser()
    if candidate.exists() and candidate.is_dir():
        return candidate
    for base in [Path("runs"), Path.cwd() / "runs"]:
        path = base / path_or_id
        if path.exists() and path.is_dir():
            return path
    return None
