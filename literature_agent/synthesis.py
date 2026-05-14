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
        "core_idea": "discrete search over RNA sequences guided by folding objectives such as base-pair distance, ensemble defect, structure probability, GC content, or benchmark success.",
        "typical_pipeline": "initialize candidate sequences, mutate or greedily edit positions, fold candidates with a prediction engine, score against the target, and keep improved designs until convergence.",
        "input": "Target secondary structure or structural constraint.",
        "output": "One or many candidate sequences optimized for folding-engine objectives.",
        "typical_metrics": "Solved benchmark count, base-pair distance, ensemble defect, MFE match, runtime.",
        "best_for": "Secondary-structure design, benchmark puzzles, interpretable optimization baselines.",
        "strengths": ["Transparent objective functions", "Does not require large training data", "Often easy to reproduce when code is available"],
        "limitations": ["Can depend strongly on folding-engine assumptions", "Search may scale poorly for long or complex targets", "Usually weaker at direct 3D design"],
    },
    "Geometric Deep Learning": {
        "core_idea": "represent RNA structures as graphs, coordinates, or backbones and learn structure-conditioned sequence generation or scoring.",
        "typical_pipeline": "encode the target 2D/3D structure with graph or geometric features, decode nucleotides conditioned on local and global context, then validate generated sequences with folding or structural metrics.",
        "input": "RNA backbone, tertiary structure, graph representation, or structural features.",
        "output": "Designed RNA sequences conditioned on geometric structure.",
        "typical_metrics": "Native sequence recovery, structural similarity, design success, runtime, generalization to held-out structures.",
        "best_for": "3D RNA inverse design and structure-aware sequence generation.",
        "strengths": ["Captures structural context beyond dot-bracket strings", "Can generate sequences quickly after training", "Naturally handles local geometric constraints"],
        "limitations": ["Depends on scarce RNA structural data", "Native recovery may not equal functional folding", "Model behavior can be hard to interpret"],
    },
    "Diffusion / Generative Models": {
        "core_idea": "learn a conditional generative process that transforms noise or random sequences into RNA designs compatible with a target structure.",
        "typical_pipeline": "condition a denoising, flow, or generative model on the target structure, sample candidate sequences, tune diversity versus fidelity, and evaluate folded structures or recovery.",
        "input": "Target tertiary structure, backbone features, or structural constraints.",
        "output": "Diverse sequence candidates sampled from a learned conditional distribution.",
        "typical_metrics": "Sequence recovery, diversity, structural similarity, self-consistency, benchmark success.",
        "best_for": "Exploring multiple plausible designs and modeling one-to-many structure-to-sequence mappings.",
        "strengths": ["Supports diverse candidate generation", "Can model non-unique design spaces", "Pairs well with structural conditioning"],
        "limitations": ["Training and sampling are more complex", "Validation still depends on downstream folding or structure predictors", "May require substantial data and compute"],
    },
    "Reinforcement Learning": {
        "core_idea": "optimize a design policy with rewards that better match the desired folding or structural outcome.",
        "typical_pipeline": "start from a generator or editable sequence policy, score sampled designs with task rewards, update the policy, and use self-consistency or structural metrics to select final candidates.",
        "input": "Target structure plus reward definitions for sequence or structure fidelity.",
        "output": "Sequences optimized for explicit task rewards.",
        "typical_metrics": "Reward score, structural similarity, RMSD or self-consistency metrics, recovery, success rate.",
        "best_for": "Cases where the desired design objective is not captured by supervised sequence recovery.",
        "strengths": ["Can optimize direct downstream objectives", "Can improve a pretrained generator", "Makes evaluation criteria explicit"],
        "limitations": ["Reward design is delicate", "Optimization can overfit proxy metrics", "Often needs expensive evaluation loops"],
    },
    "Language Models": {
        "core_idea": "treat RNA design as conditional sequence modeling, using learned nucleotide distributions to generate sequences under structural or controllability constraints.",
        "typical_pipeline": "train or adapt a sequence model, condition generation on structural information or prompts, sample with decoding controls, and validate sequence-structure compatibility.",
        "input": "Sequence context plus structural condition, tokenized constraint, or learned representation.",
        "output": "Generated RNA sequences with controllable properties.",
        "typical_metrics": "Recovery, full-structure match, perplexity-like scores, controllability, runtime.",
        "best_for": "Longer sequences, efficient generation, and integration with foundation-model representations.",
        "strengths": ["Scales well as sequence data grows", "Can support controllable decoding", "May capture long-range dependencies"],
        "limitations": ["Structural grounding can be indirect", "Needs careful validation", "Generated sequences may satisfy model likelihood without satisfying folding constraints"],
    },
    "Thermodynamic / Folding Engine": {
        "core_idea": "use explicit folding models, free-energy objectives, or folding-engine behavior as the scoring backbone for design and evaluation.",
        "typical_pipeline": "predict folding ensembles or MFE structures, compute energy/defect/probability metrics, and use those metrics to guide optimization or benchmark interpretation.",
        "input": "Target secondary structure, candidate sequence, and folding-engine parameters.",
        "output": "Scores, folded structures, or sequences selected by thermodynamic criteria.",
        "typical_metrics": "Free energy, ensemble defect, MFE agreement, structure probability, benchmark difficulty.",
        "best_for": "Interpretable baselines, validation layers, and secondary-structure tasks.",
        "strengths": ["Mechanistically interpretable", "Widely used for validation", "Important for comparing old and new methods"],
        "limitations": ["Sensitive to parameter sets and engine versions", "Secondary-structure focus can miss 3D constraints", "Energy models are approximations"],
    },
    "Benchmark / Designability": {
        "core_idea": "study which RNA structures are designable, how difficult benchmarks are, and whether evaluation protocols fairly compare methods.",
        "typical_pipeline": "define benchmark structures, run design methods or analytical bounds, compare success and difficulty, and identify motifs or conditions that drive failures.",
        "input": "Benchmark sets, target structures, folding-engine outputs, or designability formulations.",
        "output": "Difficulty estimates, benchmark results, designability bounds, or evaluation protocols.",
        "typical_metrics": "Solved targets, designability probability bounds, success rate, difficulty ranking, engine sensitivity.",
        "best_for": "Understanding field progress and avoiding misleading method comparisons.",
        "strengths": ["Clarifies evaluation standards", "Identifies hard structures and failure modes", "Helps separate method progress from benchmark artifacts"],
        "limitations": ["May not propose a new design engine", "Conclusions depend on benchmark choice", "Can lag behind fast-moving generative models"],
    },
    "Other Computational Method": {
        "core_idea": "use a computational strategy that does not cleanly fit the main method families but is still relevant to RNA sequence design.",
        "typical_pipeline": "define the target task, encode sequence or structure features, optimize or score candidates, and validate with available metadata or benchmarks.",
        "input": "Task-specific RNA sequence or structure features.",
        "output": "Predictions, scores, or candidate designs.",
        "typical_metrics": "Task-specific performance metrics reported by the source.",
        "best_for": "Specialized tasks adjacent to the main inverse-folding problem.",
        "strengths": ["Can address niche constraints", "May complement major method families"],
        "limitations": ["Evidence may be less directly comparable", "May be adjacent rather than central to inverse folding"],
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
        "matrix": matrix[:40],
    }
    result = run_prompt_json(
        client,
        "synthesis",
        fallback=fallback,
        payload=json.dumps(payload, ensure_ascii=False),
    )
    return normalize_synthesis(result, fallback)


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
                "summary": "The retrieved corpus does not contain enough core evidence to support a method-level synthesis.",
                "core_idea": "MATERIAL GAP",
                "typical_pipeline": "MATERIAL GAP",
                "strengths": [],
                "limitations": ["The corpus needs broader or more precise retrieval before a reliable review can be written."],
            }
        )
    years = [item.paper.year for item in core_items if item.paper.year]
    year_span = f"{min(years)}-{max(years)}" if years else "unknown years"
    paper_summaries = [_paper_summary(item, next((row for row in matrix if row["citation_key"] == item.citation_key), None)) for item in core_items]
    method_comparison = [_method_comparison_entry(theme) for theme in themes if theme["name"] != "MATERIAL GAP"]
    return {
        "field_overview": {
            "background": (
                "RNA inverse folding asks how to design nucleotide sequences that are expected to fold into a specified target structure. "
                "The problem matters because RNA function is tightly coupled to structure, and engineered RNA molecules are increasingly used in synthetic biology, therapeutics, sensing, and molecular programming."
            ),
            "problem_definition": (
                "In computational terms, the input is usually a target secondary structure, tertiary backbone, or structural constraint set; the output is one or more RNA sequences whose predicted ensemble or 3D conformation matches the target. "
                "The difficulty comes from the many-to-one sequence-structure map, imperfect folding models, sparse 3D structural data, and the gap between sequence recovery and actual folding fidelity."
            ),
            "why_it_matters": (
                "A useful review of this field therefore has to distinguish optimization-based design, learned scoring and generation, 3D geometric models, diffusion or flow models, reinforcement-learning refinement, language models, and benchmark/designability studies."
            ),
            "scope_note": (
                "This synthesis is limited to the screened corpus and should treat metadata-only papers more cautiously than papers with downloaded full text."
            ),
        },
        "method_evolution": [
            f"The retrieved core corpus spans {year_span}. Earlier work in the corpus is dominated by secondary-structure design, folding-engine sensitivity, and optimization benchmarks, while recent work increasingly focuses on learned structure-conditioned generation.",
            "A recurring shift is from designing sequences that satisfy a thermodynamic or ensemble objective toward models that generate candidates directly from structural representations and then validate them with folding or self-consistency metrics.",
            "The newest 3D-oriented papers treat native sequence recovery as an incomplete proxy and place more emphasis on structural fidelity, diversity, designability, and downstream validation.",
        ],
        "themes": themes,
        "method_taxonomy": themes,
        "paper_summaries": paper_summaries,
        "method_comparison": method_comparison,
        "research_trends": [
            "Secondary-structure inverse folding remains the conceptual baseline, especially for benchmark-driven optimization and Eterna-style tasks.",
            "3D-aware models are becoming a central stream because tertiary structure captures constraints that dot-bracket secondary structures cannot express.",
            "Generative models, diffusion/flow methods, and language models are moving the field from local sequence search toward learned conditional generation.",
            "Reinforcement learning and self-consistency objectives are used to optimize what the final design should do, not merely how similar it is to a native sequence.",
            "Benchmarks and designability analysis are increasingly important because different folding engines and metrics can change which method appears successful.",
        ],
        "contradictions": [
            "Native sequence recovery and structural fidelity may not measure the same design property; report claims should distinguish them.",
            "Code-required filtering improves reproducibility but can exclude foundational or survey work.",
        ],
        "knowledge_gaps": [
            "Wet-lab validation and standardized evaluation are unevenly represented in metadata-only retrieval.",
            "Open PDF availability is incomplete, so some result-level claims should remain cautious.",
        ],
        "follow_up_keywords": list(dict.fromkeys(plan.search_queries + [f"{plan.recommended_query} benchmark", f"{plan.recommended_query} wet lab validation"]))[:12],
        "limitations": [
            "Synthesis is based on verified metadata, abstracts, and downloaded open PDFs only.",
            "Sources labeled adjacent are not used as primary evidence for core conclusions unless explicitly marked.",
            f"Protocol: {protocol.research_question}",
        ],
    }


def normalize_synthesis(result: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    normalized = {}
    normalized["field_overview"] = _normalize_dict(result.get("field_overview"), fallback["field_overview"])
    for key in ["method_evolution", "research_trends", "contradictions", "knowledge_gaps", "follow_up_keywords", "limitations"]:
        value = result.get(key)
        normalized[key] = [str(item) for item in value if str(item).strip()] if isinstance(value, list) else fallback[key]
    themes = result.get("themes")
    if isinstance(themes, list):
        normalized["themes"] = [
            {
                "name": str(theme.get("name") or "Theme"),
                "evidence_strength": str(theme.get("evidence_strength") or "Emerging"),
                "citation_keys": [str(key) for key in (theme.get("citation_keys") or [])],
                "summary": str(theme.get("summary") or ""),
                "core_idea": str(theme.get("core_idea") or ""),
                "typical_pipeline": str(theme.get("typical_pipeline") or ""),
                "strengths": _string_list(theme.get("strengths")),
                "limitations": _string_list(theme.get("limitations")),
            }
            for theme in themes
            if isinstance(theme, dict)
        ] or fallback["themes"]
    else:
        normalized["themes"] = fallback["themes"]
    normalized["method_taxonomy"] = _normalize_taxonomy(result.get("method_taxonomy"), normalized["themes"], fallback["method_taxonomy"])
    normalized["paper_summaries"] = _normalize_paper_summaries(result.get("paper_summaries"), fallback["paper_summaries"])
    normalized["method_comparison"] = _normalize_method_comparison(result.get("method_comparison"), fallback["method_comparison"])
    return normalized


def _taxonomy_entry(category: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    profile = METHOD_PROFILES.get(category, METHOD_PROFILES["Other Computational Method"])
    keys = [row["citation_key"] for row in rows]
    titles = [row["title"] for row in rows[:4]]
    summary = (
        f"{category} papers in this corpus use {profile['core_idea'].lower()} "
        f"Representative examples include {', '.join(titles) if titles else 'MATERIAL GAP'}. "
        f"The common workflow is: {profile['typical_pipeline']}"
    )
    return {
        "name": category,
        "evidence_strength": "Strong" if len(rows) >= 4 else "Moderate" if len(rows) >= 2 else "Emerging",
        "citation_keys": keys[:8],
        "summary": summary,
        "core_idea": profile["core_idea"],
        "typical_pipeline": profile["typical_pipeline"],
        "representative_papers": keys[:5],
        "strengths": profile["strengths"],
        "limitations": profile["limitations"],
    }


def _paper_summary(item: CorpusItem, row: dict[str, Any] | None) -> dict[str, Any]:
    paper = item.paper
    method = row.get("method_category") if row else infer_method_category(paper.title, paper.abstract or "")
    task = row.get("task") if row else infer_task(paper.title, paper.abstract or "")
    evidence_basis = row.get("evidence_basis") if row else ("fulltext+metadata" if paper.raw.get("fulltext_path") else "metadata_or_abstract_only")
    contribution = _contribution_sentence(paper.title, paper.abstract or "", method)
    code_status = "public code was found" if (paper.github_url or paper.code_url) else "no public code link was found in collected metadata"
    pdf_status = "an open PDF URL was found" if paper.pdf_url else "no open PDF URL was found"
    summary = (
        f"{paper.title} ({paper.year or 'n.d.'}) is categorized as {method} for {task}. "
        f"{contribution} In the collected evidence, {code_status}, and {pdf_status}. "
        f"Evidence basis: {evidence_basis}; claims should be read with this limitation in mind."
    )
    return {
        "citation_key": item.citation_key,
        "title": paper.title,
        "year": paper.year,
        "method_category": method,
        "task": task,
        "summary": summary,
        "evidence_basis": evidence_basis,
        "code_url": paper.github_url or paper.code_url,
        "pdf_url": paper.pdf_url,
        "limitations": row.get("limitations", []) if row else infer_limitations(paper.abstract or "", item.inclusion.label),
    }


def _contribution_sentence(title: str, abstract: str, method: str) -> str:
    text = f"{title} {abstract}".lower()
    if "rider" in text or "reinforcement" in text:
        return "Its contribution is to connect structure-conditioned generation with reward-driven optimization so that generated sequences are judged by structural self-consistency rather than sequence recovery alone."
    if "ribodiffusion" in text or "diffusion" in text:
        return "Its contribution is to frame inverse folding as conditional generative denoising, where candidate RNA sequences are iteratively produced under structural constraints."
    if "grnade" in text or "geometric" in text or "gnn" in text:
        return "Its contribution is to encode RNA structure as a geometric graph or backbone representation and decode sequences conditioned on that geometry."
    if "samfeo" in text or "ensemble" in text:
        return "Its contribution is to optimize structure-aware ensemble objectives, producing candidate sequences that satisfy probabilistic or defect-based folding criteria."
    if "arnaque" in text or "evolutionary" in text or "greedy" in text:
        return "Its contribution is to search the discrete RNA sequence space with heuristic or evolutionary mutations guided by folding-based objectives."
    if "rwkv" in text or "language model" in text:
        return "Its contribution is to cast RNA inverse folding as conditional sequence modeling, using efficient neural sequence generation rather than explicit local search."
    if "designability" in text or "benchmark" in text or "eterna" in text:
        return "Its contribution is to clarify which structures are easy or difficult to design and how benchmark or folding-engine choices affect evaluation."
    return f"Its contribution fits the {method.lower()} stream identified from the title, abstract, and retrieved metadata."


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
        return fallback
    result = dict(fallback)
    for key in fallback:
        if value.get(key):
            result[key] = str(value[key])
    return result


def _string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


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
                "representative_papers": _string_list(item.get("representative_papers") or item.get("citation_keys")),
                "strengths": _string_list(item.get("strengths")) or profile["strengths"],
                "limitations": _string_list(item.get("limitations")) or profile["limitations"],
            }
        )
    return normalized or fallback


def _normalize_paper_summaries(value, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return fallback
    summaries = []
    for item in value:
        if not isinstance(item, dict) or not item.get("citation_key"):
            continue
        summaries.append(
            {
                "citation_key": str(item.get("citation_key")),
                "title": str(item.get("title") or ""),
                "year": item.get("year"),
                "method_category": str(item.get("method_category") or "Other Computational Method"),
                "task": str(item.get("task") or ""),
                "summary": str(item.get("summary") or ""),
                "evidence_basis": str(item.get("evidence_basis") or "metadata_or_abstract_only"),
                "code_url": item.get("code_url"),
                "pdf_url": item.get("pdf_url"),
                "limitations": _string_list(item.get("limitations")),
            }
        )
    if not summaries:
        return fallback
    seen = {item["citation_key"] for item in summaries}
    summaries.extend(item for item in fallback if item.get("citation_key") not in seen)
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
                "algorithm_pattern": str(item.get("algorithm_pattern") or ""),
                "typical_metrics": str(item.get("typical_metrics") or ""),
                "best_for": str(item.get("best_for") or ""),
                "limitations": str(item.get("limitations") or ""),
                "representative_papers": str(item.get("representative_papers") or ""),
            }
        )
    return rows or fallback


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
        limitations.append("Benchmark evidence not obvious from metadata.")
    return limitations[:3]


def synthesis_summary_counts(matrix: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(row["method_category"] for row in matrix if row.get("inclusion_label") == "core"))
