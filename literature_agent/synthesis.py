from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any

from .models import CorpusItem, ResearchProtocol, SearchPlan
from .openai_client import OpenAIClient
from .prompts import run_prompt_json


METHOD_PATTERNS = [
    ("Diffusion / Generative Models", ["diffusion", "flow matching", "generative"]),
    ("Geometric Deep Learning", ["geometric", "graph neural", "gnn", "backbone", "3d"]),
    ("Reinforcement Learning", ["reinforcement", "policy gradient", "reward"]),
    ("Evolutionary / Heuristic Optimization", ["evolutionary", "greedy", "levy", "optimization", "ensemble defect"]),
    ("Language Models", ["language model", "rwkv", "transformer", "foundation model"]),
    ("Thermodynamic / Folding Engine", ["thermodynamic", "free energy", "mfe", "vienna", "mxfold"]),
    ("Benchmark / Designability", ["benchmark", "eterna100", "designability", "probabilistic"]),
]


METHOD_PROFILES: dict[str, dict[str, Any]] = {
    "Evolutionary / Heuristic Optimization": {
        "core_idea": (
            "Discrete search over RNA sequences guided by folding objectives such as base-pair distance, "
            "ensemble defect, sequence probability, and benchmark difficulty."
        ),
        "typical_pipeline": "Initialize candidates, mutate or greedily edit positions, fold candidates via a folding engine, "
        "score against target constraints, and keep improved sequences until convergence.",
        "pipeline_steps": [
            "Define structure and constraints.",
            "Generate initial sequence pool.",
            "Evaluate candidates with folding / structure scoring.",
            "Apply mutation / optimization updates.",
            "Validate selected designs on benchmark tasks.",
        ],
        "data_domains": ["BioMed", "General ML"],
        "input": "Target secondary structure, constraints, and optimization budget.",
        "output": "Optimized nucleotide designs and difficulty-related metrics.",
        "typical_metrics": "Solved target count, ensemble defect, structure matching, runtime.",
        "best_for": "Secondary-structure baselines and interpretable optimization pipelines.",
        "strengths": ["Interpretable objectives", "No heavy model training needed", "Strong as a comparison baseline"],
        "limitations": [
            "Scales poorly for long sequences",
            "Sensitive to folding-engine configuration",
            "Coverage bias toward secondary-structure formulations",
        ],
    },
    "Geometric Deep Learning": {
        "core_idea": (
            "Represent RNA structure as graphs or geometric features and learn sequence-conditioned models "
            "for structure-aware generation or scoring."
        ),
        "typical_pipeline": "Encode structure with geometric descriptors, generate or evaluate candidates with neural networks, "
        "and validate through folding-like constraints and structure metrics.",
        "pipeline_steps": [
            "Build 2D/3D structural representation.",
            "Learn graph or coordinate-aware encoder.",
            "Condition model on structural context.",
            "Generate or score sequences.",
            "Evaluate structural consistency and benchmark performance.",
        ],
        "data_domains": ["BioMed", "Computer Vision-inspired modeling"],
        "input": "Target structure or geometric descriptors and optional folding context.",
        "output": "Structure-aware sequence candidates.",
        "typical_metrics": "Structural consistency, recovery, diversity, benchmark success.",
        "best_for": "3D-aware inverse-design and geometry-constrained problems.",
        "strengths": [
            "Captures non-local structure relationships",
            "Useful for tertiary-structure-aware design",
            "Generally stronger than pure secondary-structure search in 3D tasks",
        ],
        "limitations": [
            "Needs structured structural data",
            "Potentially heavy compute",
            "May be harder to interpret than optimization baselines",
        ],
    },
    "Diffusion / Generative Models": {
        "core_idea": (
            "Learn a conditional generative process that maps noise and structure conditions into sequence candidates."
        ),
        "typical_pipeline": "Condition a denoising/flow model on structural constraints, iteratively sample sequences, "
        "and post-validate with folding or downstream predictors.",
        "pipeline_steps": [
            "Encode structural conditions.",
            "Run conditioned iterative sampling.",
            "Enforce validity constraints during denoising.",
            "Rank candidates with structural / folding checks.",
            "Select robust candidates across multiple runs.",
        ],
        "data_domains": ["BioMed", "General AI"],
        "input": "Structure conditions (sequence motif, secondary/tertiary constraints).",
        "output": "Diverse candidate sequences from learned conditional distribution.",
        "typical_metrics": "Sequence recovery, diversity, fold success, consistency.",
        "best_for": "One-to-many design settings and exploration of complex design spaces.",
        "strengths": [
            "Supports rich multimodal/structured generation",
            "Can represent multiple valid designs",
            "High throughput after training",
        ],
        "limitations": [
            "Training/pipeline complexity",
            "Evidence often relies on proxy metrics",
            "Sampling costs can be non-trivial",
        ],
    },
    "Reinforcement Learning": {
        "core_idea": "Frame design as reward-driven optimization where reward reflects structural and task constraints.",
        "typical_pipeline": "Start from a generator, repeatedly sample, evaluate structural reward, and improve policies by optimization.",
        "pipeline_steps": [
            "Define structural/task reward.",
            "Train or fine-tune a generation policy.",
            "Sample candidate sequences.",
            "Score candidates with reward and penalties.",
            "Iterate on policy based on return.",
        ],
        "data_domains": ["BioMed", "General AI"],
        "input": "Structure-target constraints and reward design.",
        "output": "Policy-optimized designs aligned with task objectives.",
        "typical_metrics": "Reward, success rate, downstream fidelity, structural match.",
        "best_for": "Design objectives that are not recoverability-only.",
        "strengths": [
            "Optimizes explicit objective",
            "Can integrate diverse constraints",
            "Useful for self-consistency/validity shaping",
        ],
        "limitations": [
            "Reward engineering is fragile",
            "Can overfit proxy metrics",
            "High evaluation cost in loops",
        ],
    },
    "Language Models": {
        "core_idea": "Treat inverse design as conditional sequence modeling with explicit structure or control tokens.",
        "typical_pipeline": "Train/adapt a sequence model, condition on structure, decode candidates, validate structure-compatibility.",
        "pipeline_steps": [
            "Prepare structure-conditioned training data.",
            "Fine-tune or prompt-condition model.",
            "Sample sequences under constraints.",
            "Validate with folding-like checks.",
            "Return top designs for benchmark protocols.",
        ],
        "data_domains": ["BioMed", "General NLP-inspired AI"],
        "input": "Structural context, constraints, optional prompt/conditioning.",
        "output": "Conditioned design sequences.",
        "typical_metrics": "Recovery, structural fidelity, controllability, generation quality.",
        "best_for": "Scenarios with large sequence corpora and structured prompts.",
        "strengths": ["Scalable training", "Good long-range dependency modeling", "Can integrate control prompts"],
        "limitations": ["Need careful grounding", "Large-scale data bias", "High compute for pretraining/fine-tuning"],
    },
    "Thermodynamic / Folding Engine": {
        "core_idea": (
            "Use explicit free-energy and folding-model objective as the scoring core, often for benchmarking and comparison."
        ),
        "typical_pipeline": "Predict folding ensembles, compute thermodynamic/energetic scores, and guide optimization / validation.",
        "pipeline_steps": [
            "Define folding objective and engine settings.",
            "Predict candidate structures.",
            "Compute energetic metrics and distance metrics.",
            "Optimize sequence choices for target consistency.",
            "Validate by independent checks and benchmark tasks.",
        ],
        "data_domains": ["BioMed", "Computational Chemistry-influenced"],
        "input": "Target structure and scoring engine configuration.",
        "output": "Thermodynamic scores and candidate sequences.",
        "typical_metrics": "Free energy, ensemble defect, MFE agreement, fold match.",
        "best_for": "Interpretability and baseline standardization in benchmarks.",
        "strengths": [
            "Mechanistically interpretable",
            "Easy to standardize across methods",
            "Strong comparative baseline",
        ],
        "limitations": [
            "Engine-dependent outcomes",
            "Often misses full 3D constraints",
            "Model mismatch can skew comparisons",
        ],
    },
    "Benchmark / Designability": {
        "core_idea": (
            "Analyze benchmark designability, difficulty and protocol sensitivity rather than introducing a single new model."
        ),
        "typical_pipeline": "Define benchmark structures, run competing methods, inspect protocol effects, and estimate designability properties.",
        "pipeline_steps": [
            "Construct fair benchmark protocol.",
            "Compare method outputs under same settings.",
            "Measure solved rates and difficulty.",
            "Quantify sensitivity to engine/metric choices.",
            "Report method-dependent strengths and failure modes.",
        ],
        "data_domains": ["BioMed", "Methodological Studies"],
        "input": "Benchmark sets, method outputs, protocol metadata.",
        "output": "Difficulty estimates, designability observations, comparative reports.",
        "typical_metrics": "Solved rate, failure modes, ranking stability, protocol sensitivity.",
        "best_for": "Meta-analysis and evidence interpretation.",
        "strengths": ["Clarifies reproducibility issues", "Controls inflated claims", "Highlights hard cases"],
        "limitations": [
            "Requires strict protocol design",
            "Can lag behind algorithm innovation",
            "May underrepresent frontier method behavior",
        ],
    },
    "Other Computational Method": {
        "core_idea": "Method variations that do not match the major families but remain relevant to inverse folding.",
        "typical_pipeline": "Define task-specific objective and features, perform scoring or optimization, validate with available evidence.",
        "pipeline_steps": [
            "Define task-specific constraints",
            "Build objective/features",
            "Run optimization or prediction",
            "Validate with folding / benchmark checks",
            "Compare with adjacent evidence",
        ],
        "data_domains": ["BioMed", "General AI"],
        "input": "Task-specific structure and sequence features.",
        "output": "Predictions / candidate sequences.",
        "typical_metrics": "Task-dependent metrics in abstract or code.",
        "best_for": "Niche sub-problems not covered by main families.",
        "strengths": ["High flexibility", "Can target domain-specific constraints"],
        "limitations": ["Limited comparability", "Evidence coverage may be fragmented"],
    },
}


def build_literature_matrix(items: list[CorpusItem]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        paper = item.paper
        rows.append(
            {
                "citation_key": item.citation_key,
                "title": paper.title,
                "authors": paper.authors[:8],
                "year": paper.year,
                "venue": paper.venue,
                "abstract_excerpt": (paper.abstract or "")[:1400],
                "method_category": infer_method_category(paper.title, paper.abstract or ""),
                "task": infer_task(paper.title, paper.abstract or ""),
                "evidence_basis": "fulltext+metadata" if item.paper.raw.get("fulltext_path") else "metadata_or_abstract_only",
                "metrics_or_results": extract_metric_hints(paper.abstract or ""),
                "code_url": paper.github_url or paper.code_url,
                "pdf_url": paper.pdf_url,
                "inclusion_label": item.inclusion.label,
                "inclusion_reason": item.inclusion.reason,
                "limitations": infer_limitations(paper.abstract or "", item.inclusion.label),
            }
        )
    return rows


def build_synthesis(
    core_items: list[CorpusItem],
    adjacent_items: list[CorpusItem],
    matrix: list[dict[str, Any]],
    plan: SearchPlan,
    protocol: ResearchProtocol,
    client: OpenAIClient | None,
) -> dict[str, Any]:
    fallback = fallback_synthesis(core_items, adjacent_items, matrix, plan, protocol)
    if not client or not client.available or not core_items:
        return fallback

    payload = {
        "research_question": protocol.research_question,
        "plan": plan.to_dict(),
        "papers": [
            {
                "citation_key": item.citation_key,
                "title": item.paper.title,
                "authors": item.paper.authors[:5],
                "year": item.paper.year,
                "venue": item.paper.venue,
                "abstract": (item.paper.abstract or "")[:1200],
                "code_url": item.paper.github_url or item.paper.code_url,
                "pdf_url": item.paper.pdf_url,
            }
            for item in core_items[:40]
        ],
        "matrix": matrix[:80],
        "adjacent_examples": [
            {
                "citation_key": item.citation_key,
                "title": item.paper.title,
            }
            for item in adjacent_items[:20]
        ],
    }

    result = run_prompt_json(
        client,
        "synthesis",
        fallback=fallback,
        payload=json.dumps(payload, ensure_ascii=False),
    )
    normalized = normalize_synthesis(result, fallback)

    if _needs_repair(normalized, core_items):
        repaired = run_prompt_json(
            client,
            "synthesis_repair",
            fallback=normalized,
            understanding=protocol.research_question,
            plan=plan.to_dict(),
            synthesis=json.dumps(normalized, ensure_ascii=False),
            matrix=json.dumps(matrix[:80], ensure_ascii=False),
        )
        normalized = normalize_synthesis(repaired, fallback)

    return _enforce_minimum_depth(normalized, core_items, matrix)


def fallback_synthesis(
    core_items: list[CorpusItem],
    adjacent_items: list[CorpusItem],
    matrix: list[dict[str, Any]],
    plan: SearchPlan,
    protocol: ResearchProtocol,
) -> dict[str, Any]:
    categories = defaultdict(list)
    for row in matrix:
        if row["inclusion_label"] == "core":
            categories[row["method_category"]].append(row)

    themes = [
        _taxonomy_entry(category, rows)
        for category, rows in sorted(categories.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    if not themes:
        themes.append(
            {
                "name": "MATERIAL GAP",
                "evidence_strength": "Emerging",
                "citation_keys": [],
                "summary": (
                    "The retrieved corpus does not contain enough high-confidence core evidence to support a reliable "
                    "method-level synthesis. The report is constrained to a conservative evidence-oriented draft."
                ),
                "core_idea": "MATERIAL GAP",
                "typical_pipeline": "MATERIAL GAP",
                "representative_papers": [],
                "pipeline_steps": ["Collect evidence", "Mark uncertainty", "Re-scope claims"],
                "data_domains": ["BioMed"],
                "strengths": [],
                "limitations": [
                    "The corpus needs broader and more precise retrieval before detailed taxonomic synthesis can be written."
                ],
            }
        )
    years = [item.paper.year for item in core_items if item.paper.year]
    year_span = f"{min(years)}-{max(years)}" if years else "unknown years"
    paper_summaries = [
        _paper_summary(item, next((row for row in matrix if row["citation_key"] == item.citation_key), None))
        for item in core_items
    ]
    method_comparison = [_method_comparison_entry(theme) for theme in themes if theme["name"] != "MATERIAL GAP"]
    return {
        "field_overview": {
            "background": _compose_background(core_items, protocol),
            "problem_definition": _compose_problem_definition(core_items, plan, protocol),
            "why_it_matters": _compose_why_it_matters(core_items),
            "scope_note": (
                "This fallback synthesis is evidence-constrained by screened papers and their metadata; metadata-only records "
                "are treated with lower confidence than items with open PDF."
            ),
            "research_questions": _compose_research_questions(protocol.research_question, plan),
            "applicable_domains": ["BioMed", "AI for Science", "Computational Biology", "Method Development"],
        },
        "method_evolution": [
            f"The core corpus spans {year_span}, with stronger optimization baselines early and learning-based structure-conditioned methods increasing recently.",
            "A notable shift is from sequence-first optimization to structure-aware generation and multi-objective validation.",
            "Recent work tends to separate generation quality from structural fidelity by introducing task-specific validation metrics.",
        ],
        "themes": themes,
        "method_taxonomy": themes,
        "paper_summaries": paper_summaries,
        "method_comparison": method_comparison,
        "research_trends": [
            "Secondary-structure inverse folding remains a foundational baseline through benchmarks and algorithmic baselines.",
            "Tertiary-aware representations are rising because 3D constraints reduce ambiguity in sequence-to-structure mapping.",
            "Generative and RL-augmented paradigms are increasingly used to jointly optimize structure and objective constraints.",
            "Designability analyses are becoming necessary to interpret apparent benchmark gains across papers.",
        ],
        "contradictions": [
            "Sequence recovery and structural fidelity are not equivalent; each paper must be read with that distinction.",
            "Code-filtered retrieval improves reproducibility but may lose historical, survey, or baseline works.",
        ],
        "evidence_map": [
            {
                "claim": "Core methods are still clustered around structure-conditioned optimization and generative modeling.",
                "citation_keys": [item.citation_key for item in core_items[:4]],
                "strength": "moderate" if len(core_items) > 1 else "emerging",
                "basis": "method taxonomy / corpus scan",
            }
        ],
        "knowledge_gaps": [
            "Wet-lab validation remains uneven and usually incomplete in retrieved metadata.",
            "Open fulltext availability is still sparse; full methodological comparison should be cautious.",
        ],
        "follow_up_keywords": (
            list(
                dict.fromkeys(
                    plan.search_queries
                    + [f"{plan.recommended_query} benchmark", f"{plan.recommended_query} wet lab", f"{plan.recommended_query} reproducibility"]
                )
            )
        )[:14],
        "limitations": [
            "Synthesis uses screened corpus only.",
            "Adjunct corpus items are background context unless explicitly included.",
            f"Protocol constraint: {protocol.research_question}",
        ],
    }


def normalize_synthesis(result: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    normalized = {}
    normalized["field_overview"] = _normalize_field_overview(result.get("field_overview"), fallback["field_overview"])
    for key in ["method_evolution", "research_trends", "contradictions", "knowledge_gaps", "follow_up_keywords", "limitations"]:
        value = result.get(key)
        normalized[key] = _string_list(value) if isinstance(value, list) else list(fallback[key])
    evidence_map = result.get("evidence_map")
    normalized["evidence_map"] = _normalize_evidence_map(evidence_map, fallback.get("evidence_map", []))

    themes = result.get("themes")
    if isinstance(themes, list) and themes:
        normalized["themes"] = [_normalize_theme(theme) for theme in themes if isinstance(theme, dict)]
    else:
        normalized["themes"] = fallback["themes"]

    normalized["method_taxonomy"] = _normalize_taxonomy(
        result.get("method_taxonomy"),
        normalized["themes"],
        fallback["method_taxonomy"],
    )
    normalized["paper_summaries"] = _normalize_paper_summaries(
        result.get("paper_summaries"),
        fallback["paper_summaries"],
        matrix = None,
    )
    normalized["method_comparison"] = _normalize_method_comparison(
        result.get("method_comparison"),
        fallback["method_comparison"],
    )

    # maintain compatibility for existing report code that still reads method_evolution from report.research_trends
    if not normalized["research_trends"]:
        normalized["research_trends"] = normalized.get("method_evolution", []) or fallback.get("research_trends", [])
    return normalized


def _needs_repair(synthesis: dict[str, Any], core_items: list[CorpusItem]) -> bool:
    fo = synthesis.get("field_overview", {})
    if not _string_list(fo.get("research_questions")):
        return True
    if not synthesis.get("method_taxonomy"):
        return True
    if not synthesis.get("paper_summaries"):
        return True
    if not all(isinstance(method.get("representative_papers"), list) and method["representative_papers"] for method in synthesis["method_taxonomy"]):
        # if all methods are gap-like while there are core papers, request a stronger constrained rewrite
        if core_items:
            return True
    for summary in synthesis["paper_summaries"]:
        if summary.get("citation_key") in {item.citation_key for item in core_items}:
            if not summary.get("task_definition") or not summary.get("method") or not summary.get("contributions"):
                return True
    return False


def _enforce_minimum_depth(
    synthesis: dict[str, Any], core_items: list[CorpusItem], matrix: list[dict[str, Any]]
) -> dict[str, Any]:
    core_keys = {item.citation_key for item in core_items}
    summary_keys = {str(item.get("citation_key")) for item in synthesis.get("paper_summaries", [])}
    for item in core_items:
        if item.citation_key not in summary_keys:
            synthesis.setdefault("paper_summaries", []).append(
                {
                    "citation_key": item.citation_key,
                    "title": item.paper.title,
                    "year": item.paper.year,
                    "task": infer_task(item.paper.title, item.paper.abstract or ""),
                    "research_question": synthesis.get("field_overview", {}).get("research_questions", ["RQ1"])[0]
                    if synthesis.get("field_overview", {}).get("research_questions")
                    else "RQ1",
                    "method": infer_method_category(item.paper.title, item.paper.abstract or ""),
                    "contributions": "MATERIAL GAP",
                    "results_signal": "MATERIAL GAP",
                    "reproducibility": "Open code or fulltext evidence not found." if not (item.paper.github_url or item.paper.code_url) else "Open resources found",
                    "evidence_basis": "metadata_or_abstract_only",
                    "method_category": infer_method_category(item.paper.title, item.paper.abstract or ""),
                    "limitations": ["Need improved source coverage and/or full-text evidence."],
                }
            )

    # Keep order aligned to core paper order for deterministic reporting
    ordered: list[dict[str, Any]] = []
    existing = {str(item.get("citation_key")): item for item in synthesis.get("paper_summaries", [])}
    for item in core_items:
        summary = existing.get(item.citation_key)
        if summary:
            ordered.append(summary)
    for item in synthesis.get("paper_summaries", []):
        if item.get("citation_key") not in core_keys:
            ordered.append(item)
    synthesis["paper_summaries"] = ordered

    # attach matrix-informed evidence basis when available
    matrix_by_key = {row.get("citation_key"): row for row in matrix}
    for summary in synthesis["paper_summaries"]:
        if not summary.get("task_definition"):
            summary["task_definition"] = infer_task(" ".join([summary.get("title", ""), summary.get("method", "")]), "")
        row = matrix_by_key.get(summary.get("citation_key"))
        if row and row.get("evidence_basis"):
            summary["evidence_basis"] = row.get("evidence_basis")
    if not synthesis["field_overview"].get("research_questions"):
        synthesis["field_overview"]["research_questions"] = _compose_research_questions(
            synthesis.get("field_overview", {}).get("background", "RQ: unknown"), SearchPlan("", "", [], [], None, 0)
        )
    return synthesis


def _compose_background(core_items: list[CorpusItem], protocol: ResearchProtocol) -> str:
    if not core_items:
        return (
            f"{protocol.research_question} 的核心问题与可复现性仍受到检索规模和可访问全文的限制，目前证据更偏向可公开验证的摘要级信息。"
        )
    years = [item.paper.year for item in core_items if item.paper.year]
    year_range = f"{min(years)}-{max(years)}" if years else "近年"
    return (
        f"{protocol.research_question} 的检索语料主要覆盖 {year_range} 的 RNA / 结构生物学与相关计算方法。"
        f" 关注点集中在如何从结构约束约束下生成满足要求的 RNA 序列，以及可比较的验证指标。"
    )


def _compose_problem_definition(core_items: list[CorpusItem], plan: SearchPlan, protocol: ResearchProtocol) -> str:
    domains = []
    for item in core_items:
        if item.paper.venue and item.paper.venue.lower() in {"icml", "cvpr", "iclr", "acl", "neurips", "emnlp"}:
            domains.append(item.paper.venue)
    domain_tag = ", ".join(sorted(set(domains))) or "结构生物学与 AI"
    return (
        f"研究问题可抽象为：给定目标结构条件（如二级/三级结构或约束集合），生成可复现且在评测集上有效的 RNA 序列。"
        f" 输入域包括 {domain_tag}，目标域包括可达性、结构保真性和代码可复现性。"
    )


def _compose_why_it_matters(core_items: list[CorpusItem]) -> str:
    if not core_items:
        return "RNA 结构设计是序列功能工程和治疗相关生物分子的关键底层问题；可复现与可验证能力直接影响工程可落地性。"
    venues = sorted({item.paper.venue or "" for item in core_items if item.paper.venue})
    if venues:
        return f"与 {', '.join(venues[:3])} 等高水平发表/讨论语境相关，核心意义在于提升可设计性与对接真实实验或工程场景。"
    return "该方向连接了结构建模、序列生成和实验验证，核心意义在于将可解释与可复现性要求同时纳入技术路线。"


def _compose_research_questions(protocol_query: str, plan: SearchPlan) -> list[str]:
    normalized = [q.strip(" -") for q in re.findall(r"[^;,.，。；\n]+", protocol_query) if q.strip()]
    if not normalized:
        normalized = [plan.recommended_query]
    research_questions = [f"RQ1: {normalized[0]}"]
    if plan.recommended_query and plan.recommended_query not in normalized[0]:
        research_questions.append(f"RQ2: 如何比较 {plan.recommended_query} 在可复现性和结构一致性上的方法差异？")
    if not any("代码" in text or "code" in text.lower() for text in normalized):
        research_questions.append("RQ3: 哪些论文在公开代码/开源工具链层面可支持复现？")
    return research_questions


def _taxonomy_entry(category: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    profile = METHOD_PROFILES.get(category, METHOD_PROFILES["Other Computational Method"])
    keys = [row["citation_key"] for row in rows]
    titles = [row["title"] for row in rows[:4]]
    summary = (
        f"{category} 在当前语料中的主线强调 {profile['core_idea'].lower()}， "
        f"代表论文包括 {', '.join(titles) if titles else 'MATERIAL GAP'}。 "
        f"典型流程: {profile['typical_pipeline']}"
    )
    return {
        "name": category,
        "evidence_strength": "Strong" if len(rows) >= 4 else "Moderate" if len(rows) >= 2 else "Emerging",
        "citation_keys": keys[:8],
        "summary": summary,
        "core_idea": profile["core_idea"],
        "typical_pipeline": profile["typical_pipeline"],
        "pipeline_steps": profile.get("pipeline_steps", []),
        "data_domains": profile.get("data_domains", []),
        "representative_papers": keys[:5],
        "strengths": profile["strengths"],
        "limitations": profile["limitations"],
        "applicable_scenarios": profile.get("best_for", ""),
    }


def _normalize_theme(theme: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(theme.get("name") or "Method"),
        "evidence_strength": str(theme.get("evidence_strength") or "Emerging"),
        "citation_keys": _string_list(theme.get("citation_keys") or []),
        "summary": str(theme.get("summary") or ""),
        "core_idea": str(theme.get("core_idea") or ""),
        "typical_pipeline": str(theme.get("typical_pipeline") or ""),
        "pipeline_steps": _string_list(theme.get("pipeline_steps") or theme.get("steps") or []),
        "representative_papers": _string_list(theme.get("representative_papers") or theme.get("citation_keys")),
        "data_domains": _string_list(theme.get("data_domains") or []),
        "applicable_scenarios": str(theme.get("applicable_scenarios") or theme.get("best_for") or ""),
        "strengths": _string_list(theme.get("strengths")),
        "limitations": _string_list(theme.get("limitations")),
    }


def _paper_summary(item: CorpusItem, row: dict[str, Any] | None) -> dict[str, Any]:
    paper = item.paper
    method = row.get("method_category") if row else infer_method_category(paper.title, paper.abstract or "")
    task = row.get("task") if row else infer_task(paper.title, paper.abstract or "")
    evidence_basis = row.get("evidence_basis") if row else ("fulltext+metadata" if paper.raw.get("fulltext_path") else "metadata_or_abstract_only")
    contribution = _contribution_sentence(paper.title, paper.abstract or "", method)
    method_sentence = (
        "其方法是对 target structure 条件下进行序列候选生成和评估，并通过 folding 或 benchmark 约束作验证。"
    )
    result_signal = _extract_result_signal(paper.abstract or "")
    code_status = "public code was found" if (paper.github_url or paper.code_url) else "no public code link was found"
    pdf_status = "an open PDF URL was found" if paper.pdf_url else "no open PDF URL was found"
    return {
        "citation_key": item.citation_key,
        "title": paper.title,
        "year": paper.year,
        "method": method,
        "task_definition": task,
        "research_question": f"{method} 在目标结构条件下的可实现性与验证。",
        "contributions": contribution,
        "results_signal": result_signal or "MATERIAL GAP",
        "reproducibility": f"{code_status}，并且{pdf_status}。",
        "evidence_basis": evidence_basis,
        "method_category": method,
        "method_outline": method_sentence,
        "code_url": paper.github_url or paper.code_url,
        "pdf_url": paper.pdf_url,
        "limitations": row.get("limitations", []) if row else infer_limitations(paper.abstract or "", item.inclusion.label),
    }


def _extract_result_signal(text: str) -> str:
    if not text:
        return "MATERIAL GAP"
    metric_hint = re.findall(r"(?:success|solv|recovery|accuracy|MFE|RMSD|AUC|F1|precision|recall|Fidelity)[^\\.;,:！。]{0,60}", text, flags=re.I)
    return metric_hint[0][:140] + "..." if metric_hint else "MATERIAL GAP"


def _contribution_sentence(title: str, abstract: str, method: str) -> str:
    text = f"{title} {abstract}".lower()
    if "rider" in text or "reinforcement" in text:
        return "其核心贡献在于通过结构条件与策略优化融合，强化候选序列的结构一致性与任务目标约束。"
    if "ribodiffusion" in text or "diffusion" in text:
        return "其核心贡献是将逆折叠建模为条件生成任务，通过扩散/流匹配生成兼顾结构约束的候选序列。"
    if "gRNAde".lower() in text or "geometric" in text or "gnn" in text:
        return "其核心贡献在于使用结构几何表示将序列生成/评估从二级结构转向三维或几何感知框架。"
    if "samfeo" in text or "ensemble" in text:
        return "其核心贡献是将序列设计转化为设计性可控的集合优化问题，强调结构可行性而非单一恢复指标。"
    if "arnaque" in text or "evolutionary" in text or "greedy" in text:
        return "其核心贡献在于通过进化/启发式搜索平衡多目标约束，提高可达结构下的序列可行率。"
    if "language model" in text or "rwkv" in text:
        return "其核心贡献在于将 RNA 设计问题转成条件化序列建模任务，增强可控采样与序列一致性。"
    if "benchmark" in text or "designability" in text or "eterna" in text:
        return "其核心贡献在于量化不同结构/方法的可设计性差异，厘清评测规范对“方法性能”结论的影响。"
    return f"其贡献定位于 {method} 路线，提供可复现性相关的结构生成或验证框架。"


def _method_comparison_entry(theme: dict[str, Any]) -> dict[str, str]:
    profile = METHOD_PROFILES.get(theme["name"], METHOD_PROFILES["Other Computational Method"])
    return {
        "method_category": theme["name"],
        "input": profile["input"],
        "output": profile["output"],
        "algorithm_pattern": profile["typical_pipeline"],
        "typical_metrics": profile["typical_metrics"],
        "best_for": profile["best_for"],
        "limitations": "; ".join(profile["limitations"]),
        "representative_papers": ", ".join(theme.get("citation_keys", [])[:5]),
    }


def _normalize_dict(value, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return dict(fallback)
    result = dict(fallback)
    for key in fallback:
        if value.get(key):
            result[key] = _coerce_value(value.get(key), fallback[key])
    return result


def _normalize_field_overview(value, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    result = dict(fallback)
    for key, field in [
        ("background", ""),
        ("problem_definition", ""),
        ("why_it_matters", ""),
        ("scope_note", ""),
    ]:
        value_item = value.get(key)
        if isinstance(value_item, str) and value_item.strip():
            result[key] = value_item.strip()
        elif value_item and not isinstance(fallback.get(key), str):
            result[key] = _coerce_value(value_item, fallback.get(key))
    result["research_questions"] = _string_list(value.get("research_questions")) or fallback.get("research_questions", [])
    result["applicable_domains"] = _string_list(value.get("applicable_domains")) or fallback.get("applicable_domains", [])
    return result


def _normalize_evidence_map(value, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return list(fallback)
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        keys = _string_list(item.get("citation_keys") or [])
        normalized.append(
            {
                "claim": str(item.get("claim") or ""),
                "citation_keys": keys,
                "strength": str(item.get("strength") or "emerging"),
                "basis": str(item.get("basis") or "synthesis"),
            }
        )
    if not normalized:
        return list(fallback)
    return normalized


def _normalize_paper_summaries(
    value,
    fallback: list[dict[str, Any]],
    matrix: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return list(fallback)
    summaries = []
    matrix_by_key = {row["citation_key"]: row for row in (matrix or [])}
    for item in value:
        if not isinstance(item, dict):
            continue
        citation_key = str(item.get("citation_key") or "").strip()
        if not citation_key:
            continue
        row = matrix_by_key.get(citation_key, {})
        summaries.append(
            {
                "citation_key": citation_key,
                "title": str(item.get("title") or ""),
                "year": item.get("year"),
                "method": str(item.get("method") or row.get("method_category") or "Other Computational Method"),
                "method_category": str(item.get("method_category") or row.get("method_category") or "Other Computational Method"),
                "task": str(item.get("task") or item.get("task_definition") or ""),
                "task_definition": str(item.get("task_definition") or item.get("task") or ""),
                "research_question": str(item.get("research_question") or ""),
                "contributions": str(item.get("contributions") or ""),
                "results_signal": str(item.get("results_signal") or ""),
                "reproducibility": str(item.get("reproducibility") or ""),
                "evidence_basis": str(item.get("evidence_basis") or row.get("evidence_basis") or "metadata_or_abstract_only"),
                "code_url": item.get("code_url"),
                "pdf_url": item.get("pdf_url"),
                "limitations": _string_list(item.get("limitations")),
                "method_outline": str(item.get("method_outline") or ""),
            }
        )
    if not summaries:
        return list(fallback)
    return summaries


def _normalize_method_comparison(value, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return fallback
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "method_category": str(item.get("method_category") or item.get("name") or "Method"),
                "input": str(item.get("input") or ""),
                "output": str(item.get("output") or ""),
                "algorithm_pattern": str(item.get("algorithm_pattern") or item.get("typical_pipeline") or ""),
                "typical_metrics": str(item.get("typical_metrics") or ""),
                "best_for": str(item.get("best_for") or ""),
                "limitations": str(item.get("limitations") or ""),
                "representative_papers": str(item.get("representative_papers") or item.get("citation_keys") or ""),
            }
        )
    return rows or fallback


def _normalize_taxonomy(value, themes: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source = value if isinstance(value, list) and value else themes
    normalized = []
    for item in source:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("method_category") or "Method")
        profile = METHOD_PROFILES.get(name, METHOD_PROFILES["Other Computational Method"])
        normalized.append(
            {
                "name": name,
                "core_idea": str(item.get("core_idea") or profile["core_idea"]),
                "typical_pipeline": str(item.get("typical_pipeline") or profile["typical_pipeline"]),
                "pipeline_steps": _string_list(item.get("pipeline_steps") or profile.get("pipeline_steps", [])),
                "data_domains": _string_list(item.get("data_domains") or profile.get("data_domains", [])),
                "applicable_scenarios": str(item.get("applicable_scenarios") or profile.get("best_for", "")),
                "representative_papers": _string_list(item.get("representative_papers") or item.get("citation_keys")),
                "evidence_strength": str(item.get("evidence_strength") or "Emerging"),
                "strengths": _string_list(item.get("strengths")) or profile["strengths"],
                "limitations": _string_list(item.get("limitations")) or profile["limitations"],
                "research_questions": _string_list(item.get("research_questions")),
            }
        )
    return normalized or fallback


def _coerce_value(value: Any, fallback: Any) -> Any:
    if isinstance(fallback, list):
        return _string_list(value)
    if isinstance(fallback, str):
        return str(value).strip()
    return value


def _string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, set):
        return [str(item).strip() for item in sorted(value) if str(item).strip()]
    if isinstance(value, str):
        return [segment.strip() for segment in value.split(";") if segment.strip()]
    return []


def _infer_matrix_by_key(matrix: list[dict[str, Any]], keys: set[str]) -> list[dict[str, Any]]:
    return [row for row in matrix if str(row.get("citation_key")) in keys]


def infer_method_category(title: str, abstract: str) -> str:
    text = f"{title} {abstract}".lower()
    scores = []
    for category, terms in METHOD_PATTERNS:
        score = sum(1 for term in terms if term in text)
        scores.append((score, category))
    best_score, best_category = max(scores, key=lambda item: item[0])
    return best_category if best_score else "Other Computational Method"


def infer_task(title: str, abstract: str) -> str:
    text = f"{title} {abstract}".lower()
    if "inverse" in text or "design" in text:
        if "3d" in text or "tertiary" in text or "backbone" in text:
            return "3D RNA inverse design"
        return "RNA sequence design / inverse folding"
    if "prediction" in text:
        return "RNA structure prediction"
    if "benchmark" in text or "eterna" in text:
        return "Benchmarking"
    return "Adjacent computational RNA task"


def extract_metric_hints(text: str) -> list[str]:
    hints = re.findall(r"(?:\d+(?:\.\d+)?\s*%|[<>]=?\s*\d+(?:\.\d+)?|AUC|RMSD|F1|accuracy|recovery|success rate)", text, flags=re.I)
    return list(dict.fromkeys(hints))[:8]


def infer_limitations(abstract: str, label: str) -> list[str]:
    limitations = []
    if label != "core":
        limitations.append("Adjacent or excluded item; not primary evidence for core synthesis.")
    if not abstract:
        limitations.append("No abstract available in collected metadata.")
    if "benchmark" not in abstract.lower() and "dataset" not in abstract.lower():
        limitations.append("Benchmark protocol visibility is limited from metadata.")
    return limitations[:3]


def _paper_summary_sort_key(summary: dict[str, Any]) -> str:
    return str(summary.get("title") or "")


def synthesis_summary_counts(matrix: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(row["method_category"] for row in matrix if row.get("inclusion_label") == "core"))
