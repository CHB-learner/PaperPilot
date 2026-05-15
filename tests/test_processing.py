import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import contextlib
import io

from literature_agent.config import (
    AppConfig,
    config_delete,
    config_use,
    load_app_config,
    load_user_config,
    mask_secret,
    read_profile_file,
    save_app_config,
    save_user_config,
)
from literature_agent.cli import build_parser
from literature_agent.cli import main as cli_main
from literature_agent.corpus import corpus_items_from_papers, enhanced_deduplicate, split_corpus
from literature_agent.intent import ParsedIntent, parse_research_intent, parse_research_intent_with_llm
from literature_agent.models import Paper
from literature_agent.openai_client import OpenAIClient
from literature_agent.pdf_report import write_pdf_report
from literature_agent.planner import make_plan
from literature_agent.protocol import build_protocol
from literature_agent.processing import apply_github_filter, deduplicate, resolve_code_links
from literature_agent.query import heuristic_understanding
from literature_agent.report import build_canonical_report, render_html_reports, render_reports
from literature_agent.searchers import search_dblp, search_europe_pmc, search_pubmed
from literature_agent.sources import SourceConfig, resolve_enabled_sources
from literature_agent.synthesis import build_literature_matrix, build_synthesis
from literature_agent.ui import console as rich_console
from literature_agent.ui import print_intent_summary, print_sources_table, source_status_summary
from literature_agent.utils import create_task_dir, read_api_config
from literature_agent.utils import ApiConfig
from literature_agent.verification import build_quality_gate, verify_corpus
import literature_agent.workflow as workflow_module


class ProcessingTests(unittest.TestCase):
    def test_deduplicate_prefers_doi(self):
        papers = [
            Paper(title="A Paper", doi="10.1/example", source="crossref", sources=["crossref"]),
            Paper(title="A Paper", doi="10.1/example", source="openalex", sources=["openalex"], pdf_url="https://example.org/a.pdf"),
        ]

        merged = deduplicate(papers)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].pdf_url, "https://example.org/a.pdf")
        self.assertEqual(set(merged[0].sources), {"crossref", "openalex"})

    def test_resolve_code_links_and_filter_required(self):
        papers = [
            Paper(title="With Code", abstract="Code: https://github.com/example/repo"),
            Paper(title="Without Code", abstract="No implementation is available."),
        ]

        resolved = resolve_code_links(papers)
        filtered = apply_github_filter(resolved, "required")

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].github_url, "https://github.com/example/repo")

    def test_paper_model_normalizes_non_string_metadata(self):
        paper = Paper(
            title={"value": "RNA inverse folding"},
            authors=[{"name": "Ada Lovelace"}],
            venue={"display_name": "Nature Biotechnology"},
            abstract=["RNA", "sequence design"],
        )

        ranked = workflow_module.rank_papers([paper], "RNA sequence design", 2021)

        self.assertEqual(ranked[0].venue, "Nature Biotechnology")
        self.assertEqual(ranked[0].authors, ["Ada Lovelace"])
        self.assertGreaterEqual(ranked[0].rank_score, 0)

    def test_project_pdf_is_not_code_link(self):
        papers = [
            Paper(
                title="Not Code",
                abstract="See https://projecteuclid.org/journals/example/paper.pdf",
            )
        ]

        resolved = resolve_code_links(papers)

        self.assertFalse(resolved[0].has_code)

    def test_rna_is_ambiguous_and_ai_scoped(self):
        result = heuristic_understanding("RNA")

        self.assertTrue(result.needs_confirmation)
        self.assertIn("RNA foundation model", result.search_terms)

    def test_parse_chinese_interactive_intent(self):
        result = parse_research_intent("调研RNA逆折叠 序列设计 近五年的文献，要求有代码仓库的,方法不限", current_year=2026)

        self.assertEqual(result.keyword, "RNA逆折叠 序列设计")
        self.assertEqual(result.since_year, 2021)
        self.assertEqual(result.github_filter, "required")
        self.assertTrue(result.auto_confirm)
        self.assertIn("RNA逆折叠 序列设计 github", result.search_terms)

    def test_llm_intent_parser_falls_back_without_client(self):
        result = parse_research_intent_with_llm("调研RNA逆折叠 序列设计 近五年的文献，要求有代码仓库的", None, current_year=2026)

        self.assertEqual(result.keyword, "RNA逆折叠 序列设计")
        self.assertGreaterEqual(len(result.search_terms), 4)

    def test_planner_merges_seed_search_terms(self):
        understanding = heuristic_understanding("RNA逆折叠 序列设计")
        plan = make_plan(
            understanding,
            max_papers=20,
            since_year=2021,
            client=None,
            seed_search_terms=["RNA inverse folding", "RNA sequence design github"],
        )

        self.assertEqual(plan.search_queries[0], "RNA inverse folding")
        self.assertIn("RNA sequence design github", plan.search_queries)

    def test_read_api_config_two_line_base_url_and_key(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "llmapi.txt"
            path.write_text("https://api.deepseek.com\nsk-example\n", encoding="utf-8")

            config = read_api_config(path)

            self.assertEqual(config.base_url, "https://api.deepseek.com")
            self.assertEqual(config.api_key, "sk-example")

    def test_read_profile_file_allows_trailing_comma(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "api.json"
            path.write_text(
                '{"api_key":"sk-example","base_url":"https://api.deepseek.com","model":"deepseek-chat",}',
                encoding="utf-8",
            )

            profile = read_profile_file(path)

            self.assertEqual(profile["api_key"], "sk-example")
            self.assertEqual(profile["base_url"], "https://api.deepseek.com")
            self.assertEqual(profile["model"], "deepseek-chat")

    def test_write_pdf_report(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.zh.pdf"

            write_pdf_report("# 中文报告\n\n## 研究背景\n\n- RNA inverse folding 序列设计\n", path, title="中文调研报告")

            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 1000)

    def test_create_task_dir_is_unique(self):
        with TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)

            first_id, first_path = create_task_dir("RNA inverse folding", runs_dir)
            second_id, second_path = create_task_dir("RNA inverse folding", runs_dir)

            self.assertNotEqual(first_id, second_id)
            self.assertNotEqual(first_path, second_path)
            self.assertTrue(first_path.exists())
            self.assertTrue(second_path.exists())

    def test_user_config_roundtrip(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            save_user_config(ApiConfig(api_key="sk-example", base_url="https://api.deepseek.com", model="deepseek-chat"), path)

            config = load_user_config(path)

            self.assertEqual(config.api_key, "sk-example")
            self.assertEqual(config.base_url, "https://api.deepseek.com")
            self.assertEqual(config.model, "deepseek-chat")

    def test_app_config_multiple_profiles(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            save_app_config(
                AppConfig(
                    active="deepseek",
                    profiles={
                        "deepseek": ApiConfig(api_key="sk-ds", base_url="https://api.deepseek.com", model="deepseek-chat"),
                        "openai": ApiConfig(api_key="sk-openai", model="gpt-5.2"),
                    },
                ),
                path,
            )

            config = load_app_config(path)

            self.assertEqual(config.active, "deepseek")
            self.assertEqual(set(config.profiles), {"deepseek", "openai"})
            self.assertEqual(load_user_config(path).model, "deepseek-chat")

    def test_app_config_source_settings_roundtrip(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            save_app_config(
                AppConfig(
                    active=None,
                    profiles={},
                    sources={"core": SourceConfig(enabled=True, api_key="core-key")},
                ),
                path,
            )

            config = load_app_config(path)

            self.assertTrue(config.sources["core"].enabled)
            self.assertEqual(config.sources["core"].api_key, "core-key")

    def test_source_presets_enable_expected_domains(self):
        biomed = set(resolve_enabled_sources("biomed"))
        cs = set(resolve_enabled_sources("cs"))

        self.assertIn("pubmed", biomed)
        self.assertIn("europe_pmc", biomed)
        self.assertIn("dblp", cs)
        self.assertIn("acl_anthology", cs)
        self.assertNotIn("pubmed", cs)

    def test_optional_source_requires_configuration(self):
        self.assertNotIn("core", resolve_enabled_sources("all"))
        enabled = resolve_enabled_sources("all", {"core": SourceConfig(api_key="core-key")})
        self.assertIn("core", enabled)

    def test_rich_source_summary_counts_configured_optional_sources(self):
        summary = source_status_summary({"core": SourceConfig(api_key="core-key")}, mode="auto")

        self.assertGreater(summary.enabled_free, 0)
        self.assertEqual(summary.configured_optional, 1)
        self.assertIn("core", summary.enabled_sources)
        self.assertNotIn("core", summary.missing_optional)

    def test_rich_intent_and_sources_render_without_terminal(self):
        intent = ParsedIntent(
            keyword="RNA inverse folding",
            search_terms=["RNA inverse folding", "RNA sequence design github"],
            since_year=2021,
            max_papers=20,
            github_filter="required",
            no_download=True,
            auto_confirm=True,
            notes=["unit test"],
        )

        with rich_console.capture() as capture:
            print_intent_summary(intent, source_mode="biomed")
            print_sources_table({"core": SourceConfig(api_key="core-key")}, mode="auto")

        output = capture.get()
        self.assertIn("Parsed Research Intent", output)
        self.assertIn("RNA inverse folding", output)
        self.assertIn("PaperPilot Sources", output)

    def test_deduplicate_uses_pubmed_and_dblp_identifiers(self):
        papers = [
            Paper(title="Biomedical Paper", raw={"identifiers": {"pmid": "123"}}),
            Paper(title="Biomedical Paper Variant", raw={"identifiers": {"pmid": "123"}}, pdf_url="https://example.org/p.pdf"),
            Paper(title="CS Paper", raw={"identifiers": {"dblp_key": "conf/acl/X"}}),
            Paper(title="CS Paper Extended", raw={"identifiers": {"dblp_key": "conf/acl/X"}}, doi="10.1/x"),
        ]

        merged = deduplicate(papers)

        self.assertEqual(len(merged), 2)
        self.assertTrue(any(p.pdf_url == "https://example.org/p.pdf" for p in merged))

    def test_parse_pubmed_response(self):
        import literature_agent.searchers as module

        esearch = {"esearchresult": {"idlist": ["123"]}}
        xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>RNA inverse folding with AI</ArticleTitle><Abstract><AbstractText>Sequence design.</AbstractText></Abstract><Journal><Title>Nucleic Acids Research</Title><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal><AuthorList><Author><ForeName>Ada</ForeName><LastName>Lovelace</LastName></Author></AuthorList></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/rna</ArticleId><ArticleId IdType="pmc">PMC1</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""
        original_json = module.request_json
        original_text = module.request_text
        try:
            module.request_json = lambda *args, **kwargs: esearch
            module.request_text = lambda *args, **kwargs: xml

            papers = search_pubmed("RNA inverse folding", 5, 2021)

            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0].doi, "10.1/rna")
            self.assertEqual(papers[0].raw["identifiers"]["pmid"], "123")
        finally:
            module.request_json = original_json
            module.request_text = original_text

    def test_parse_europe_pmc_response(self):
        import literature_agent.searchers as module

        payload = {
            "resultList": {
                "result": [
                    {
                        "title": "RNA design with language models",
                        "authorString": "A. Author, B. Writer",
                        "pubYear": "2025",
                        "journalTitle": "Bioinformatics",
                        "abstractText": "AI sequence design.",
                        "doi": "10.1/epmc",
                        "pmid": "456",
                        "pmcid": "PMC456",
                        "citedByCount": "7",
                    }
                ]
            }
        }
        original_json = module.request_json
        try:
            module.request_json = lambda *args, **kwargs: payload

            papers = search_europe_pmc("RNA design", 5, 2021)

            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0].citation_count, 7)
            self.assertEqual(papers[0].raw["identifiers"]["pmcid"], "PMC456")
        finally:
            module.request_json = original_json

    def test_parse_dblp_response(self):
        import literature_agent.searchers as module

        payload = {
            "result": {
                "hits": {
                    "hit": [
                        {
                            "info": {
                                "title": "Agentic retrieval augmented generation",
                                "authors": {"author": [{"text": "Jane Doe"}]},
                                "year": "2024",
                                "venue": "ACL",
                                "doi": "10.1/acl",
                                "url": "https://dblp.org/rec/conf/acl/X",
                                "key": "conf/acl/X",
                            }
                        }
                    ]
                }
            }
        }
        original_json = module.request_json
        try:
            module.request_json = lambda *args, **kwargs: payload

            papers = search_dblp("agent rag", 5, 2021)

            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0].raw["identifiers"]["dblp_key"], "conf/acl/X")
        finally:
            module.request_json = original_json

    def test_mask_secret(self):
        self.assertEqual(mask_secret(None), "(not set)")
        self.assertEqual(mask_secret("sk-1234567890"), "sk-1...7890")

    def test_help_can_render_chinese_or_english(self):
        zh = build_parser("zh").format_help()
        en = build_parser("en").format_help()

        self.assertIn("AI 文献检索 Agent", zh)
        self.assertIn("最终保留论文数量", zh)
        self.assertIn("AI literature search agent", en)
        self.assertIn("Maximum ranked papers", en)

    def test_cli_version_prints_package_version(self):
        import literature_agent

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli_main(["--version"])

        self.assertEqual(code, 0)
        self.assertIn(literature_agent.__version__, buffer.getvalue())

    def test_chat_completion_uses_reasoning_content_when_content_empty(self):
        client = OpenAIClient(api_key="sk-test", model="deepseek-test", base_url="https://api.deepseek.com")
        import literature_agent.openai_client as module

        original = module.post_json
        try:
            module.post_json = lambda *args, **kwargs: {
                "choices": [{"message": {"content": "", "reasoning_content": "OK"}}]
            }

            text = client.text("test", "test", max_output_tokens=8)

            self.assertEqual(text, "OK")
        finally:
            module.post_json = original

    def test_v1_title_similarity_deduplicates_preprint_and_published_version(self):
        papers = [
            Paper(
                title="gRNAde: Geometric Deep Learning for 3D RNA inverse design",
                authors=["Chaitanya K. Joshi"],
                year=2023,
                arxiv_id="2305.14749",
                source="arxiv",
            ),
            Paper(
                title="gRNAde: Geometric Deep Learning for 3D RNA inverse design",
                authors=["Chaitanya K. Joshi"],
                year=2024,
                doi="10.1101/2024.03.31.587283",
                source="openalex",
                pdf_url="https://example.org/grnade.pdf",
            ),
        ]

        merged, stats = enhanced_deduplicate(papers)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].year, 2024)
        self.assertEqual(merged[0].pdf_url, "https://example.org/grnade.pdf")
        self.assertGreaterEqual(stats["title_similarity_merges"], 0)

    def test_v1_screening_excludes_off_topic_rna_tools(self):
        understanding = heuristic_understanding("RNA inverse folding sequence design")
        plan = make_plan(understanding, max_papers=10, since_year=2021, client=None)
        protocol = build_protocol(understanding, plan, "required", client=None)
        papers = [
            Paper(
                title="RiboDiffusion: tertiary structure-based RNA inverse folding with generative diffusion models",
                abstract="We present a diffusion model for RNA inverse folding and sequence design.",
                year=2024,
                github_url="https://github.com/ml4bio/RiboDiffusion",
                has_code=True,
            ),
            Paper(
                title="AutoDock Vina 1.2.0: New Docking Methods, Expanded Force Field, and Python Bindings",
                abstract="A molecular docking tool for ligands and proteins.",
                year=2021,
                github_url="https://github.com/ccsb-scripps/AutoDock-Vina",
                has_code=True,
            ),
            Paper(
                title="RNA-SeQC 2: efficient RNA-seq quality control and quantification for large cohorts",
                abstract="RNA-seq quality control and quantification.",
                year=2021,
                github_url="https://github.com/getzlab/rnaseqc",
                has_code=True,
            ),
        ]

        items = corpus_items_from_papers(papers, plan, protocol, client=None)
        labels = {item.paper.title: item.inclusion.label for item in items}

        self.assertEqual(labels[papers[0].title], "core")
        self.assertEqual(labels[papers[1].title], "exclude")
        self.assertEqual(labels[papers[2].title], "exclude")

    def test_v1_quality_gate_and_bilingual_report_share_same_paper_list(self):
        understanding = heuristic_understanding("RNA inverse folding sequence design")
        plan = make_plan(understanding, max_papers=10, since_year=2021, client=None)
        protocol = build_protocol(understanding, plan, "any", client=None)
        papers = [
            Paper(
                title="RIDER: 3D RNA Inverse Design with Reinforcement Learning-Guided Diffusion",
                authors=["Tao Hu"],
                year=2026,
                venue="arXiv",
                abstract="RNA inverse design with diffusion and reinforcement learning.",
                github_url="https://github.com/COLA-Laboratory/RIDER",
                has_code=True,
                pdf_url="https://arxiv.org/pdf/example",
            ),
            Paper(
                title="RNA design via structure-aware multifrontier ensemble optimization",
                authors=["T. Zhou"],
                year=2023,
                venue="Bioinformatics",
                abstract="RNA sequence design with ensemble optimization.",
                github_url="https://github.com/shanry/SAMFEO",
                has_code=True,
            ),
        ]
        items = corpus_items_from_papers(papers, plan, protocol, client=None)
        core, adjacent, excluded = split_corpus(items)
        log = [{"title": papers[0].title, "status": "downloaded", "path": "/tmp/rider.pdf", "url": papers[0].pdf_url}]
        verification = verify_corpus(items, log)
        matrix = build_literature_matrix(core)
        synthesis = build_synthesis(core, adjacent, matrix, plan, protocol, client=None)
        self.assertIn("field_overview", synthesis)
        self.assertIn("method_taxonomy", synthesis)
        self.assertIn("paper_summaries", synthesis)
        self.assertIn("method_comparison", synthesis)
        self.assertIn("research_trends", synthesis)
        self.assertEqual({item["citation_key"] for item in synthesis["paper_summaries"]}, {item.citation_key for item in core})
        self.assertNotIn("core papers in the corpus address", json.dumps(synthesis, ensure_ascii=False))
        quality = build_quality_gate(
            items,
            core,
            verification,
            log,
            max_papers=10,
            github_filter="any",
            quality="fast",
            dedup_stats={"raw_count": 2, "after_title_similarity_dedup": 2},
        )
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
            log,
            {"verdict": quality.verdict},
            mode="apa",
            include_adjacent=False,
            client=None,
        )
        zh, en = render_reports(canonical)
        zh_html, en_html = render_html_reports(canonical)

        self.assertEqual(len(canonical["papers"]), 2)
        self.assertEqual(len(canonical["paper_summaries"]), 2)
        self.assertEqual(canonical["papers"][0]["citation_label"], "[1]")
        self.assertEqual(canonical["papers"][1]["citation_label"], "[2]")
        self.assertIn("研究背景与问题定义", zh)
        self.assertIn("主流方法流派综述", zh)
        self.assertIn("代表论文总结", zh)
        self.assertIn("方法比较表", zh)
        self.assertIn("### [1] RIDER", zh)
        self.assertIn("[2] RNA design via structure-aware", zh)
        self.assertIn("Research Background and Problem Definition", en)
        self.assertIn("Main Method Families", en)
        self.assertIn("Representative Paper Summaries", en)
        self.assertIn("Method Comparison", en)
        self.assertIn("证据账本与复核 Agent", zh)
        self.assertIn("Evidence Ledger and Review Agents", en)
        self.assertIn("### [1] RIDER", en)
        self.assertIn("[2] RNA design via structure-aware", en)
        self.assertIn("RIDER", zh)
        self.assertIn("RIDER", en)
        self.assertIn("RIDER", zh_html)
        self.assertIn("RIDER", en_html)
        self.assertIn("[1] RIDER", zh_html)
        self.assertIn("[2] RNA design via structure-aware", zh_html)
        self.assertIn("参考文献", zh_html)
        self.assertIn("References", en_html)
        self.assertIn("https://github.com/COLA-Laboratory/RIDER", zh_html)
        self.assertIn("https://github.com/COLA-Laboratory/RIDER", en_html)
        self.assertNotIn("paper1", zh_html)
        self.assertNotIn("paper2", zh_html)
        self.assertIn("RNA design via structure-aware", zh)
        self.assertIn("RNA design via structure-aware", en)
        self.assertIn("<!doctype html>", zh_html)
        self.assertIn("<table>", en_html)
        self.assertIn(canonical["report_date"], zh)
        self.assertIn(canonical["report_date"], en)

    def test_v1_workflow_writes_expected_artifacts_with_mock_search(self):
        class FakeClient:
            available = False
            model = "fake"

        original_search_all = workflow_module.search_all
        try:
            workflow_module.search_all = lambda plan, per_query_limit=10: [
                Paper(
                    title="RIDER: 3D RNA Inverse Design with Reinforcement Learning-Guided Diffusion",
                    authors=["Tao Hu"],
                    year=2026,
                    venue="arXiv",
                    abstract="RNA inverse design with diffusion and reinforcement learning.",
                    github_url="https://github.com/COLA-Laboratory/RIDER",
                    has_code=True,
                    pdf_url="https://arxiv.org/pdf/example",
                    source="arxiv",
                    sources=["arxiv"],
                ),
                Paper(
                    title="AutoDock Vina 1.2.0: New Docking Methods, Expanded Force Field, and Python Bindings",
                    authors=["J. Eberhardt"],
                    year=2021,
                    abstract="A molecular docking tool.",
                    github_url="https://github.com/ccsb-scripps/AutoDock-Vina",
                    has_code=True,
                    source="openalex",
                    sources=["openalex"],
                ),
            ]
            with TemporaryDirectory() as tmp:
                args = argparse.Namespace(
                    keyword="RNA inverse folding sequence design",
                    max_papers=10,
                    since_year=2021,
                    output_dir=Path(tmp) / "run",
                    github_filter="required",
                    auto_confirm=True,
                    no_download=True,
                    pdf_limit=None,
                    github_search_limit=0,
                    seed_search_terms=["RNA inverse folding"],
                    unpaywall_email=None,
                    mode="apa",
                    interaction="auto",
                    quality="fast",
                    include_adjacent=False,
                    user_corpus=[],
                )

                with contextlib.redirect_stdout(io.StringIO()):
                    code = workflow_module.run_v1_workflow(args, FakeClient())

                self.assertEqual(code, 0)
                self.assertTrue((args.output_dir / "state.json").exists())
                self.assertTrue((args.output_dir / "events.jsonl").exists())
                self.assertTrue((args.output_dir / "prompt_manifest.json").exists())
                self.assertTrue((args.output_dir / "registries.json").exists())
                self.assertTrue((args.output_dir / "protocol.json").exists())
                self.assertTrue((args.output_dir / "user_corpus_log.json").exists())
                self.assertTrue((args.output_dir / "corpus.json").exists())
                self.assertTrue((args.output_dir / "verification.json").exists())
                self.assertTrue((args.output_dir / "quality_gate.json").exists())
                self.assertTrue((args.output_dir / "evidence_ledger.json").exists())
                self.assertTrue((args.output_dir / "review_agent_findings.json").exists())
                self.assertTrue((args.output_dir / "report.canonical.json").exists())
                self.assertTrue((args.output_dir / "report.zh.html").exists())
                self.assertTrue((args.output_dir / "report.en.html").exists())
                html = (args.output_dir / "report.zh.html").read_text(encoding="utf-8")
                self.assertIn("研究背景与问题定义", html)
                self.assertIn("代表论文总结", html)
                self.assertIn("证据账本与复核 Agent", html)
                ledger = json.loads((args.output_dir / "evidence_ledger.json").read_text(encoding="utf-8"))
                self.assertGreater(ledger["claim_count"], 0)
                review = json.loads((args.output_dir / "review_agent_findings.json").read_text(encoding="utf-8"))
                self.assertIn(review["verdict"], {"pass", "needs_attention"})
                events = (args.output_dir / "events.jsonl").read_text(encoding="utf-8")
                self.assertIn('"stage": "report"', events)
                corpus = json.loads((args.output_dir / "corpus.json").read_text(encoding="utf-8"))
                labels = {item["paper"]["title"]: item["inclusion"]["label"] for item in corpus}
                self.assertEqual(labels["AutoDock Vina 1.2.0: New Docking Methods, Expanded Force Field, and Python Bindings"], "exclude")
        finally:
            workflow_module.search_all = original_search_all


if __name__ == "__main__":
    unittest.main()
