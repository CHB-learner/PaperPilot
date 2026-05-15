import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import contextlib
import io
import os
import stat
import subprocess
import sys

from literature_agent.config import (
    AppConfig,
    config_delete,
    config_use,
    default_app_config,
    ensure_config_initialized,
    load_app_config,
    load_user_config,
    mask_secret,
    read_profile_file,
    save_app_config,
    save_user_config,
)
from literature_agent.doctor import run_doctor
from literature_agent.cli import build_parser
from literature_agent.cli import main as cli_main
from literature_agent.corpus import corpus_items_from_papers, enhanced_deduplicate, split_corpus
from literature_agent.intent import ParsedIntent, parse_research_intent, parse_research_intent_with_llm
from literature_agent.models import CorpusItem, InclusionDecision, Paper
from literature_agent.openai_client import OpenAIClient
from literature_agent.pdf_report import write_pdf_report
from literature_agent.planner import make_plan
from literature_agent.protocol import build_protocol
from literature_agent.processing import apply_github_filter, deduplicate, resolve_code_links
from literature_agent.query import heuristic_understanding
from literature_agent.report import build_canonical_report, markdown_report_to_html, render_html_reports, render_reports
from literature_agent.report_policy import select_report_items
from literature_agent.searchers import search_dblp, search_deepxiv, search_europe_pmc, search_pubmed
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
        result = parse_research_intent("调研CVPR/ICML近三年关于少样本学习在生物序列中的应用，要求有代码链接,方法不限", current_year=2026)

        self.assertIn("CVPR/ICML", result.keyword)
        self.assertIn("少样本", result.keyword)
        self.assertEqual(result.since_year, 2023)
        self.assertEqual(result.github_filter, "required")
        self.assertTrue(result.auto_confirm)
        self.assertIn("CVPR/ICML", result.keyword)
        self.assertTrue(any("生物序列" in term for term in result.search_terms))

    def test_llm_intent_parser_falls_back_without_client(self):
        result = parse_research_intent_with_llm("调研CVPR/ICML近三年关于少样本学习在生物序列中的应用，要求有代码链接", None, current_year=2026)

        self.assertIn("CVPR/ICML", result.keyword)
        self.assertIn("少样本", result.keyword)
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

    def test_html_renderer_keeps_markdown_table_rows_together(self):
        markdown = """# Report

| Source | Returned |
|---|---:|

| arXiv | 42 |

| PubMed | 92 |

Paragraph.
"""

        html = markdown_report_to_html(markdown, title="Report", lang="en")

        self.assertEqual(html.count("<table>"), 1)
        self.assertIn("<tbody>", html)
        self.assertIn("<td>arXiv</td>", html)
        self.assertIn("<td>PubMed</td>", html)

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

    def test_default_config_template_contains_empty_optional_sources(self):
        config = default_app_config()

        self.assertEqual(config.active, "default")
        self.assertIn("default", config.profiles)
        self.assertEqual(config.profiles["default"].model, "gpt-5.2")
        self.assertEqual(config.profiles["default"].api_key, "")
        self.assertEqual(set(config.sources), {"core", "lens", "ieee", "springer", "elsevier", "dimensions", "deepxiv"})
        self.assertTrue(all(source.api_key == "" for source in config.sources.values()))
        self.assertTrue(all(source.enabled is None for source in config.sources.values()))

    def test_ensure_config_initialized_writes_template_once(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "paperpilot" / "config.json"

            created = ensure_config_initialized(path)
            first = path.read_text(encoding="utf-8")
            second = ensure_config_initialized(path)
            mode = stat.S_IMODE(path.stat().st_mode)

            self.assertTrue(created)
            self.assertFalse(second)
            self.assertEqual(first, path.read_text(encoding="utf-8"))
            self.assertEqual(mode, 0o600)
            config = load_app_config(path)
            self.assertEqual(config.active, "default")
            self.assertFalse(config.profiles["default"].api_key)
            self.assertNotIn("core", resolve_enabled_sources("auto", config.sources))

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

    def test_deepxiv_source_requires_configuration_and_supports_domain_presets(self):
        self.assertNotIn("deepxiv", resolve_enabled_sources("auto"))
        enabled = set(resolve_enabled_sources("biomed", {"deepxiv": SourceConfig(api_key="deepxiv-key")}))

        self.assertIn("deepxiv", enabled)

    def test_cli_config_path_initializes_template_under_paperpilot_home(self):
        with TemporaryDirectory() as tmp:
            env = {**os.environ, "PAPERPILOT_HOME": tmp}
            result = subprocess.run(
                [sys.executable, "-m", "literature_agent.cli", "config", "path"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            config_path = Path(tmp) / "config.json"

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(config_path.exists())
            self.assertIn(str(config_path), result.stdout)
            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(data["active"], "default")
            self.assertEqual(data["sources"]["core"]["api_key"], "")

            clear = subprocess.run(
                [sys.executable, "-m", "literature_agent.cli", "config", "clear"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(clear.returncode, 0, clear.stderr)
            self.assertFalse(config_path.exists())

            sources = subprocess.run(
                [sys.executable, "-m", "literature_agent.cli", "sources", "list"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(sources.returncode, 0, sources.stderr)
            self.assertTrue(config_path.exists())
            self.assertIn("core              disabled requires-key no-key", sources.stdout)

    def test_doctor_reports_missing_llm_and_skips_unconfigured_sources(self):
        class FakeClient:
            available = False
            model = "fake"

        report = run_doctor(FakeClient(), AppConfig())

        self.assertEqual(report.verdict, "fail")
        self.assertTrue(any(check.area == "LLM" and check.status == "fail" for check in report.checks))
        self.assertTrue(any(check.name == "optional APIs" and check.status == "skip" for check in report.checks))

    def test_doctor_checks_configured_source_without_exposing_key(self):
        class FakeClient:
            available = True
            model = "fake"

            def text(self, *args, **kwargs):
                return "OK"

        import literature_agent.doctor as module

        original = module.search_one_source
        try:
            module.search_one_source = lambda *args, **kwargs: [Paper(title="RNA paper")]
            report = run_doctor(
                FakeClient(),
                AppConfig(sources={"core": SourceConfig(api_key="secret-core-key")}),
            )
        finally:
            module.search_one_source = original

        self.assertEqual(report.verdict, "pass")
        rendered = json.dumps([check.__dict__ for check in report.checks])
        self.assertNotIn("secret-core-key", rendered)
        self.assertTrue(any(check.name == "CORE" and check.status == "pass" for check in report.checks))

    def test_cli_doctor_initializes_config_and_returns_failure_without_llm(self):
        with TemporaryDirectory() as tmp:
            repo = Path(__file__).resolve().parents[1]
            env = {
                **os.environ,
                "PAPERPILOT_HOME": tmp,
                "PYTHONPATH": str(repo),
                "OPENAI_API_KEY": "",
                "OPENAI_BASE_URL": "",
                "OPENAI_MODEL": "",
            }
            result = subprocess.run(
                [sys.executable, "-m", "literature_agent.cli", "--doctor"],
                cwd=tmp,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertTrue((Path(tmp) / "config.json").exists())
            self.assertIn("PaperPilot Doctor", result.stdout)
            self.assertIn("fail", result.stdout.lower())

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

    def test_parse_papers_cool_arxiv_and_venue_html(self):
        import literature_agent.searchers as module

        arxiv_html = """
        <div id=\"2401.00001\" class=\"panel paper\">
          <a id=\"title-2401.00001\" href=\"/paper/2401.00001\">RNA inverse folding with attention</a>
          <p id=\"summary-2401.00001\">A generative model for RNA design.</p>
          <p id=\"authors-2401.00001\"><a>Ann Lee</a>, <a>Ben Zhou</a></p>
          <p id=\"date-2401.00001\"><span class=\"date-data\">2024</span></p>
          <p id=\"subjects-2401.00001\">cs.AI</p>
          <a id=\"pdf-2401.00001\" data=\"https://papers.cool/papers/2401.00001.pdf\">PDF</a>
        </div>
        <div id=\"conf.2025\" class=\"panel paper\">
          <a id=\"title-conf.2025\" href=\"/paper/conf\">Conference RNA design benchmarks</a>
          <p id=\"summary-conf.2025\">Benchmarking framework for structural design.</p>
          <p id=\"authors-conf.2025\"><a>Carol Wu</a></p>
          <p id=\"subjects-conf.2025\">bioinformatics</p>
          <a id=\"pdf-conf.2025\" data=\"https://papers.cool/papers/conf.pdf\">PDF</a>
        </div>
        """
        venue_html = """
        <div id=\"conf.2025\" class=\"panel paper\">
          <a id=\"title-conf.2025\" href=\"https://papers.cool/venue/conf/\">RNA sequence design venue paper</a>
          <p id=\"summary-conf.2025\">A venue search result.</p>
          <p id=\"authors-conf.2025\"><a>Dana Kim</a>, <a>Tom Lee</a></p>
          <p id=\"date-conf.2025\">2025</p>
          <p id=\"subjects-conf.2025\">RNA, structure</p>
          <a id=\"pdf-conf.2025\" data=\"/pdf/conf-1.pdf\">PDF</a>
        </div>
        """
        with self.subTest("arxiv search mode"):
            papers = module._parse_papers_cool_html(arxiv_html, "RNA inverse folding", "arxiv")
            self.assertEqual(len(papers), 2)
            self.assertEqual(papers[0].source, "papers_cool")
            self.assertEqual(papers[0].title, "RNA inverse folding with attention")
            self.assertEqual(papers[0].year, 2024)
            self.assertEqual(papers[0].arxiv_id, "2401.00001")
            self.assertTrue(papers[0].pdf_url.endswith(".pdf"))
        with self.subTest("venue search mode"):
            papers = module._parse_papers_cool_html(venue_html, "RNA inverse folding", "venue")
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0].venue, "venue")
            self.assertEqual(papers[0].year, 2025)

    def test_papers_cool_list_pagination_uses_skip_and_show(self):
        import literature_agent.searchers as module
        from urllib.parse import parse_qs, urlparse

        def panel(idx: int) -> str:
            return f"""
            <div id=\"{idx:04d}.{idx:04d}\" class=\"panel paper\">
              <a id=\"title-{idx:04d}.{idx:04d}\" href=\"/paper/{idx:04d}.{idx:04d}\">RNA inverse folding sample {idx}</a>
              <p id=\"summary-{idx:04d}.{idx:04d}\">sample {idx} model.</p>
              <p id=\"date-{idx:04d}.{idx:04d}\">2024</p>
              <p id=\"subjects-{idx:04d}.{idx:04d}\">cs.AI</p>
              <a id=\"pdf-{idx:04d}.{idx:04d}\" data=\"/pdf/p{idx}.pdf\">PDF</a>
            </div>
            """

        first = "".join(panel(i) for i in range(20))
        second = panel(20)

        def request_text(url, *args, **kwargs):
            skip = int(parse_qs(urlparse(url).query).get("skip", ["0"])[0])
            if skip == 0:
                return first
            if skip == 20:
                return second
            return ""

        original_request_text = module.request_text
        try:
            module.request_text = request_text
            papers = module._search_papers_cool_list("arxiv", "RNA inverse folding", 21, None)
            self.assertEqual(len(papers), 21)
            self.assertEqual(papers[0].title, "RNA inverse folding sample 0")
            self.assertEqual(papers[20].title, "RNA inverse folding sample 20")
        finally:
            module.request_text = original_request_text

    def test_papers_cool_parsing_robust_to_missing_fields(self):
        import literature_agent.searchers as module

        html = """
        <div id=\"2024.00003\" class=\"panel paper\">
          <a id=\"title-2024.00003\" href=\"/paper/broken\">RNA inverse folding robustness</a>
          <p id=\"summary-broken.2024\">No authors, no date, no pdf</p>
          <p id=\"subjects-broken.2024\">systems</p>
        </div>
        """
        papers = module._parse_papers_cool_html(html, "RNA inverse folding", "arxiv")
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].year, 2024)
        self.assertEqual(papers[0].authors, [])
        self.assertIsNone(papers[0].pdf_url)

    def test_parse_deepxiv_response(self):
        import literature_agent.searchers as module

        payload = {
            "status": "success",
            "result": [
                {
                    "arxiv_id": "2603.00084",
                    "score": 0.94,
                    "title": "DeepXiv-SDK: An Agentic Data Interface for Scientific Literature",
                    "abstract": "An agentic data interface for scientific literature.",
                    "authors": [{"name": "Jane Doe"}],
                    "url": "https://arxiv.org/abs/2603.00084",
                    "date": "2026-03-01T00:00:00Z",
                    "citation_count": 3,
                    "categories": ["cs.DL"],
                }
            ],
        }
        original_sdk = module._deepxiv_sdk_search
        original_rest = module._deepxiv_rest_search
        try:
            module._deepxiv_sdk_search = lambda *args, **kwargs: payload if args[3] == "arxiv" else {"result": []}
            module._deepxiv_rest_search = lambda *args, **kwargs: {}

            papers = search_deepxiv("agentic data interface", 3, 2021, SourceConfig(api_key="deepxiv-key"))

            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0].source, "deepxiv")
            self.assertEqual(papers[0].arxiv_id, "2603.00084")
            self.assertEqual(papers[0].pdf_url, "https://arxiv.org/pdf/2603.00084")
            self.assertEqual(papers[0].citation_count, 3)
            self.assertEqual(papers[0].raw["deepxiv_source"], "arxiv")
        finally:
            module._deepxiv_sdk_search = original_sdk
            module._deepxiv_rest_search = original_rest

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

    def test_cli_rejects_report_size_below_minimum(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli_main(["RNA inverse folding", "--max-papers", "29"])

        self.assertEqual(code, 2)

    def test_report_selection_fills_to_thirty_with_adjacent_items(self):
        core = [
            CorpusItem(
                citation_key=f"core{i}",
                paper=Paper(title=f"Core RNA inverse folding paper {i}", has_code=True),
                inclusion=InclusionDecision(label="core", score=0.9, reason="core"),
            )
            for i in range(10)
        ]
        adjacent = [
            CorpusItem(
                citation_key=f"adj{i}",
                paper=Paper(title=f"Adjacent RNA design paper {i}", has_code=True),
                inclusion=InclusionDecision(label="adjacent", score=0.5, reason="adjacent"),
            )
            for i in range(25)
        ]

        selection = select_report_items(core, adjacent, "required", max_papers=50, min_report_papers=30)

        self.assertIsNone(selection.shortfall)
        self.assertEqual(len(selection.items), 35)
        self.assertGreaterEqual(selection.stats["final_report_count"], 30)
        self.assertEqual(selection.stats["core_report_count"], 10)
        self.assertGreaterEqual(selection.stats["adjacent_fill_count"], 20)

    def test_report_selection_shortfall_when_screened_corpus_is_too_small(self):
        core = [
            CorpusItem(
                citation_key=f"core{i}",
                paper=Paper(title=f"Core RNA inverse folding paper {i}", has_code=True),
                inclusion=InclusionDecision(label="core", score=0.9, reason="core"),
            )
            for i in range(5)
        ]

        selection = select_report_items(core, [], "required", max_papers=50, min_report_papers=30)

        self.assertIsNotNone(selection.shortfall)
        self.assertEqual(selection.shortfall["missing_count"], 25)

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

    def test_v1_screening_adapts_to_non_rna_biomed_topic(self):
        understanding = heuristic_understanding("organoid research methods")
        plan = make_plan(
            understanding,
            max_papers=50,
            since_year=2021,
            client=None,
            seed_search_terms=[
                "organoid",
                "organoid culture method",
                "organoid review",
                "patient-derived organoid methodology",
            ],
        )
        protocol = build_protocol(understanding, plan, "any", client=None)
        papers = [
            Paper(
                title="Human organoid culture methods for disease modeling",
                abstract="This review discusses organoid culture methods and patient-derived organoid models.",
                year=2024,
            ),
            Paper(
                title="D-CryptO: Deep learning-based analysis of colon organoid morphology from brightfield images",
                abstract="Deep learning analysis of colon organoid morphology.",
                year=2022,
            ),
            Paper(
                title="RiboDiffusion: tertiary structure-based RNA inverse folding with generative diffusion models",
                abstract="RNA inverse folding and sequence design.",
                year=2024,
            ),
        ]

        items = corpus_items_from_papers(papers, plan, protocol, client=None)
        labels = {item.paper.title: item.inclusion.label for item in items}

        self.assertEqual(labels[papers[0].title], "core")
        self.assertIn(labels[papers[1].title], {"core", "adjacent"})
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
        unique_terms = [
            "Diffusion atlas",
            "Graph geometry",
            "Transformer scaffold",
            "Evolutionary search",
            "Benchmark protocol",
            "Energy landscape",
            "Tertiary motif",
            "Secondary constraint",
            "Foundation model",
            "Reward optimizer",
            "Designability suite",
            "Backbone encoder",
            "Latent sampler",
            "Hybrid folding",
            "Constraint solver",
            "Sequence generator",
            "Structure compiler",
            "Pairing grammar",
            "Neural heuristic",
            "Open benchmark",
            "Motif recovery",
            "Loop designer",
            "Helix planner",
            "Long range contact",
            "Probabilistic decoder",
            "Energy guided sampler",
            "RNA language prior",
            "Sparse graph model",
            "Thermodynamic verifier",
            "Generative evaluator",
            "Comparative study",
            "Inverse design toolkit",
            "Sequence recovery model",
            "Open source baseline",
            "Multi objective design",
        ]
        try:
            workflow_module.search_all = lambda plan, per_query_limit=10: [
                *[
                    Paper(
                        title=f"{unique_terms[idx]} for RNA inverse folding sequence design",
                        authors=[f"Author {idx}"],
                        year=2021 + (idx % 6),
                        venue="arXiv",
                        abstract="RNA inverse folding sequence design with benchmark evaluation and computational RNA design.",
                        github_url=f"https://github.com/example/rna-design-{idx}",
                        has_code=True,
                        pdf_url=f"https://arxiv.org/pdf/example{idx}",
                        source="arxiv",
                        sources=["arxiv"],
                    )
                    for idx in range(35)
                ],
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
                    max_papers=50,
                    min_report_papers=30,
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
                    no_obsidian_wiki=False,
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
                self.assertTrue((args.output_dir / "obsidian_wiki" / "index.md").exists())
                self.assertTrue((args.output_dir / "obsidian_wiki" / "_meta" / "manifest.json").exists())
                self.assertGreaterEqual(len(list((args.output_dir / "obsidian_wiki" / "papers").glob("*.md"))), 30)
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
                ranked = json.loads((args.output_dir / "ranked_papers.json").read_text(encoding="utf-8"))
                self.assertGreaterEqual(len(ranked), 30)
                lint = json.loads((args.output_dir / "obsidian_wiki" / "_meta" / "wiki_lint.json").read_text(encoding="utf-8"))
                self.assertEqual(lint["broken_wikilink_count"], 0)
        finally:
            workflow_module.search_all = original_search_all

    def test_v1_workflow_shortfall_does_not_write_formal_report(self):
        class FakeClient:
            available = False
            model = "fake"

        original_search_all = workflow_module.search_all
        try:
            workflow_module.search_all = lambda plan, per_query_limit=10: [
                Paper(
                    title=f"RNA inverse folding sequence design short corpus {idx}",
                    authors=[f"Author {idx}"],
                    year=2024,
                    abstract="RNA inverse folding sequence design with benchmark evaluation.",
                    github_url=f"https://github.com/example/short-{idx}",
                    has_code=True,
                    source="arxiv",
                    sources=["arxiv"],
                )
                for idx in range(5)
            ]
            with TemporaryDirectory() as tmp:
                args = argparse.Namespace(
                    keyword="RNA inverse folding sequence design",
                    max_papers=50,
                    min_report_papers=30,
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
                    no_obsidian_wiki=True,
                )

                with contextlib.redirect_stdout(io.StringIO()):
                    code = workflow_module.run_v1_workflow(args, FakeClient())

                self.assertEqual(code, 2)
                self.assertTrue((args.output_dir / "shortfall.json").exists())
                self.assertFalse((args.output_dir / "report.canonical.json").exists())
                self.assertFalse((args.output_dir / "obsidian_wiki").exists())
        finally:
            workflow_module.search_all = original_search_all


if __name__ == "__main__":
    unittest.main()
