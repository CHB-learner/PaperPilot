from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from . import __version__
from .config import (
    config_delete,
    config_import,
    config_use,
    load_app_config,
    load_user_config,
    print_profiles,
    run_config_command,
    save_app_config,
    test_llm_config,
)
from .intent import ParsedIntent, parse_research_intent_with_llm
from .openai_client import OpenAIClient
from .sources import run_sources_command
from .utils import read_api_config
from .workflow import inspect_run, resolve_run_dir, run_v1_workflow


def build_parser(language: str = "bilingual") -> argparse.ArgumentParser:
    text = parser_text(language)
    parser = argparse.ArgumentParser(
        prog="PaperPilot",
        description=text["description"],
        epilog=text["epilog"],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("keyword", nargs="?", help=text["keyword"])
    parser.add_argument("--max-papers", type=int, default=50, help=text["max_papers"])
    parser.add_argument("--since-year", type=int, default=2021, help=text["since_year"])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=text["output_dir"],
    )
    parser.add_argument(
        "--openai-model",
        default=os.getenv("OPENAI_MODEL", "gpt-5.2"),
        help=text["openai_model"],
    )
    parser.add_argument(
        "--openai-api-key-file",
        type=Path,
        default=Path("llmapi.txt"),
        help=text["openai_api_key_file"],
    )
    parser.add_argument(
        "--unpaywall-email",
        default=os.getenv("UNPAYWALL_EMAIL"),
        help=text["unpaywall_email"],
    )
    parser.add_argument(
        "--github-filter",
        choices=["any", "required", "none"],
        default="any",
        help=text["github_filter"],
    )
    parser.add_argument(
        "--auto-confirm",
        action="store_true",
        help=text["auto_confirm"],
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help=text["no_download"],
    )
    parser.add_argument("--pdf-limit", type=int, default=None, help=text["pdf_limit"])
    parser.add_argument(
        "--github-search-limit",
        type=int,
        default=25,
        help=text["github_search_limit"],
    )
    parser.add_argument(
        "--mode",
        choices=["quick", "apa", "systematic"],
        default="apa",
        help=text["mode"],
    )
    parser.add_argument(
        "--interaction",
        choices=["auto", "gated"],
        default="auto",
        help=text["interaction"],
    )
    parser.add_argument(
        "--quality",
        choices=["fast", "balanced", "strict"],
        default="balanced",
        help=text["quality"],
    )
    parser.add_argument(
        "--include-adjacent",
        action="store_true",
        help=text["include_adjacent"],
    )
    parser.add_argument(
        "--user-corpus",
        action="append",
        default=[],
        help=text["user_corpus"],
    )
    parser.add_argument(
        "--sources",
        choices=["auto", "all", "core", "biomed", "cs", "configured"],
        default="auto",
        help=text["sources"],
    )
    parser.add_argument(
        "--enable-source",
        action="append",
        default=[],
        help=text["enable_source"],
    )
    parser.add_argument(
        "--disable-source",
        action="append",
        default=[],
        help=text["disable_source"],
    )
    return parser


def parser_text(language: str) -> dict[str, str]:
    if language == "zh":
        return {
            "description": "AI 文献检索 Agent",
            "epilog": """
示例:
  PaperPilot
  PaperPilot config set --base-url https://api.deepseek.com --model deepseek-chat
  PaperPilot config show
  PaperPilot sources list
  PaperPilot sources config core
  PaperPilot "RNA" --auto-confirm --max-papers 50
  PaperPilot "LLM agent" --auto-confirm --github-filter required --sources cs

输出:
  task.json               任务信息
  state.json              状态机进度
  manifest.json           运行产物清单
  query_understanding.md  关键词理解
  plan.json               检索计划
  protocol.json           研究协议
  ranked_papers.json      排序后的论文
  corpus.json             带筛选标签的完整语料
  verification.json       DOI/PDF/代码验证状态
  quality_gate.json       质量门结果
  literature_matrix.json  证据矩阵
  synthesis.json          综合分析
  report.canonical.json   中英文报告共用中间表示
  report.zh.md            中文报告
  report.en.md            英文报告
  report.zh.html          中文 HTML 报告
  report.en.html          英文 HTML 报告
  report.zh.pdf           中文 PDF 报告
  report.en.pdf           英文 PDF 报告
  download_log.json       PDF 下载日志
  pdfs/                   开放 PDF 文件
  fulltext/               PDF 全文抽取文本
  events.jsonl            阶段事件流
  source_diagnostics.json 来源覆盖与错误诊断
  evidence_ledger.json    claim 级证据账本
  review_agent_findings.json  复核 Agent 检查结果
""",
            "keyword": "研究关键词或主题，例如 RNA",
            "max_papers": "最终保留论文数量，默认 50",
            "since_year": "优先检索该年份之后的论文，默认 2021",
            "output_dir": "输出目录；默认自动生成 runs/<task-id>",
            "openai_model": "OpenAI 或兼容服务的模型名，默认 gpt-5.2",
            "openai_api_key_file": "兼容旧配置文件，默认 llmapi.txt",
            "unpaywall_email": "Unpaywall 邮箱，用于补充开放 PDF 链接",
            "github_filter": "代码链接筛选：any 不过滤，required 只保留有代码，none 只保留无代码",
            "auto_confirm": "关键词宽泛或有歧义时，自动使用推荐方向继续",
            "no_download": "跳过 PDF 下载，但仍写入 download_log.json",
            "pdf_limit": "最多下载 PDF 数量",
            "github_search_limit": "主动搜索 GitHub 仓库的论文数量，默认 25",
            "mode": "报告模式：quick 快速摘要，apa 学术综述，systematic 系统综述框架；默认 apa",
            "interaction": "交互方式：auto 尽量自动，gated 关键歧义时确认；默认 auto",
            "quality": "质量门严格度：fast|balanced|strict，默认 balanced",
            "include_adjacent": "在附录/矩阵中包含相关但非核心论文",
            "user_corpus": "导入本地 PDF/BibTeX/RIS/Markdown 文件或目录，可重复传入",
            "sources": "检索来源 preset：auto|all|core|biomed|cs|configured，默认 auto",
            "enable_source": "额外启用某个来源，可重复传入",
            "disable_source": "禁用某个来源，可重复传入",
        }
    if language == "en":
        return {
            "description": "AI literature search agent",
            "epilog": """
Examples:
  PaperPilot
  PaperPilot config set --base-url https://api.deepseek.com --model deepseek-chat
  PaperPilot config show
  PaperPilot sources list
  PaperPilot sources config core
  PaperPilot "RNA" --auto-confirm --max-papers 50
  PaperPilot "LLM agent" --auto-confirm --github-filter required --sources cs

Outputs:
  task.json               Task metadata
  state.json              Workflow state
  manifest.json           Run manifest
  query_understanding.md  Query interpretation
  plan.json               Search plan
  protocol.json           Research protocol
  ranked_papers.json      Ranked papers
  corpus.json             Screened corpus with labels
  verification.json       DOI/PDF/code verification
  quality_gate.json       Quality gate result
  literature_matrix.json  Evidence matrix
  synthesis.json          Evidence synthesis
  report.canonical.json   Shared bilingual report model
  report.zh.md            Chinese report
  report.en.md            English report
  report.zh.html          Chinese HTML report
  report.en.html          English HTML report
  report.zh.pdf           Chinese PDF report
  report.en.pdf           English PDF report
  download_log.json       PDF download log
  pdfs/                   Open-access PDFs
  fulltext/               Extracted PDF text
  events.jsonl            Stage event stream
  source_diagnostics.json Source coverage and errors
  evidence_ledger.json    Claim-level evidence ledger
  review_agent_findings.json  Review-agent findings
""",
            "keyword": "Research keyword or topic, e.g. RNA",
            "max_papers": "Maximum ranked papers to keep, default: 50",
            "since_year": "Prefer papers since this year, default: 2021",
            "output_dir": "Output directory; default: auto-generated runs/<task-id>",
            "openai_model": "OpenAI or compatible model name, default: gpt-5.2",
            "openai_api_key_file": "Legacy config file, default: llmapi.txt",
            "unpaywall_email": "Unpaywall email for open PDF lookup",
            "github_filter": "Code filter: any keeps all, required keeps papers with code, none keeps papers without code",
            "auto_confirm": "Auto-confirm recommended query for broad or ambiguous keywords",
            "no_download": "Skip PDF downloads but still write download_log.json",
            "pdf_limit": "Maximum number of PDFs to download",
            "github_search_limit": "Number of papers to check with GitHub search, default: 25",
            "mode": "Report mode: quick, apa, or systematic; default: apa",
            "interaction": "Interaction mode: auto or gated; default: auto",
            "quality": "Quality gate strictness: fast|balanced|strict, default: balanced",
            "include_adjacent": "Include adjacent non-core papers in appendix/matrix",
            "user_corpus": "Import local PDF/BibTeX/RIS/Markdown file or directory; repeatable",
            "sources": "Search source preset: auto|all|core|biomed|cs|configured, default: auto",
            "enable_source": "Enable an additional source; repeatable",
            "disable_source": "Disable a source; repeatable",
        }
    return {
        "description": "AI 文献检索 Agent / AI literature search agent",
        "epilog": """
示例 / Examples:
  PaperPilot
  PaperPilot config set --base-url https://api.deepseek.com --model deepseek-chat
  PaperPilot config show
  PaperPilot sources list
  PaperPilot sources config core
  PaperPilot "RNA" --auto-confirm --max-papers 50
  PaperPilot "LLM agent" --auto-confirm --github-filter required --sources cs
  literature-agent "vision language model" --auto-confirm --no-download

输出 / Outputs:
  task.json               任务信息 / task metadata
  state.json              状态机进度 / workflow state
  manifest.json           运行产物清单 / run manifest
  query_understanding.md  关键词理解 / query interpretation
  plan.json               检索计划 / search plan
  protocol.json           研究协议 / research protocol
  ranked_papers.json      排序后的论文 / ranked papers
  corpus.json             完整筛选语料 / screened corpus
  verification.json       验证状态 / verification status
  quality_gate.json       质量门 / quality gate
  literature_matrix.json  证据矩阵 / evidence matrix
  synthesis.json          综合分析 / synthesis
  report.canonical.json   双语报告中间表示 / shared report model
  report.zh.md            中文报告 / Chinese report
  report.en.md            英文报告 / English report
  report.zh.html          中文 HTML 报告 / Chinese HTML report
  report.en.html          英文 HTML 报告 / English HTML report
  report.zh.pdf           中文 PDF 报告 / Chinese PDF report
  report.en.pdf           英文 PDF 报告 / English PDF report
  download_log.json       PDF 下载日志 / PDF download log
  pdfs/                   开放 PDF 文件 / open-access PDFs
  fulltext/               PDF 文本抽取 / extracted PDF text
  events.jsonl            阶段事件流 / stage event stream
  source_diagnostics.json 来源覆盖与错误诊断 / source coverage and errors
  evidence_ledger.json    claim 级证据账本 / claim-level evidence ledger
  review_agent_findings.json  复核 Agent 检查结果 / review-agent findings
""",
        "keyword": "研究关键词或主题，例如 RNA / Research keyword or topic, e.g. RNA",
        "max_papers": "最终保留论文数量，默认 50 / Maximum ranked papers to keep, default: 50",
        "since_year": "优先检索该年份之后的论文，默认 2021 / Prefer papers since this year, default: 2021",
        "output_dir": "输出目录；默认自动生成 runs/<task-id> / Output directory; default: auto-generated runs/<task-id>",
        "openai_model": "OpenAI 模型名，默认 gpt-5.2 / OpenAI model name, default: gpt-5.2",
        "openai_api_key_file": "兼容旧配置文件，默认 llmapi.txt / Legacy API key file, default: llmapi.txt",
        "unpaywall_email": "Unpaywall 邮箱，用于补充开放 PDF 链接 / Unpaywall email for open PDF lookup",
        "github_filter": "代码链接筛选：any 不过滤，required 只保留有代码，none 只保留无代码 / Code filter: any|required|none",
        "auto_confirm": "关键词宽泛或有歧义时，自动使用推荐方向继续 / Auto-confirm recommended query for broad or ambiguous keywords",
        "no_download": "跳过 PDF 下载，但仍写入 download_log.json / Skip PDF downloads but still write download_log.json",
        "pdf_limit": "最多下载 PDF 数量 / Maximum number of PDFs to download",
        "github_search_limit": "主动搜索 GitHub 仓库的论文数量，默认 25 / Number of papers to check with GitHub search, default: 25",
        "mode": "报告模式 quick|apa|systematic，默认 apa / Report mode, default: apa",
        "interaction": "交互方式 auto|gated，默认 auto / Interaction mode, default: auto",
        "quality": "质量门严格度 fast|balanced|strict，默认 balanced / Quality gate strictness",
        "include_adjacent": "包含相关但非核心论文 / Include adjacent non-core papers",
        "user_corpus": "导入本地语料文件或目录，可重复传入 / Import local corpus path; repeatable",
        "sources": "检索来源 preset auto|all|core|biomed|cs|configured，默认 auto / Search source preset",
        "enable_source": "额外启用来源，可重复传入 / Enable an additional source; repeatable",
        "disable_source": "禁用来源，可重复传入 / Disable a source; repeatable",
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "config":
        return run_config_command(argv[1:])
    if argv and argv[0] == "sources":
        return run_sources_command(argv[1:])
    if any(arg in {"--version", "-V"} for arg in argv):
        print(f"paperpilot {__version__}")
        return 0
    if argv and argv[0] == "inspect":
        if len(argv) < 2:
            print("Usage: PaperPilot inspect <task-id-or-run-dir>")
            return 2
        return inspect_run(argv[1])
    if argv and argv[0] == "resume":
        return resume_run(argv[1:])
    if any(arg in {"--help", "-h"} for arg in argv):
        return language_help()
    args = build_parser().parse_args(argv)
    if not args.keyword:
        return interactive_main(args)
    return run_agent(args)


def language_help() -> int:
    print("请选择帮助语言 / Choose help language:")
    print("  1. 中文")
    print("  2. English")
    try:
        choice = input("选择 / Choice [1]: ").strip().lower()
    except EOFError:
        choice = "1"
    language = "en" if choice in {"2", "en", "english", "e"} else "zh"
    print()
    print(build_parser(language).format_help())
    return 0


def resume_run(argv: list[str]) -> int:
    if not argv:
        print("Usage: PaperPilot resume <task-id-or-run-dir>")
        return 2
    run_dir = resolve_run_dir(argv[0])
    if not run_dir:
        print(f"Run not found: {argv[0]}")
        return 1
    task_path = run_dir / "task.json"
    if not task_path.exists():
        print(f"Missing task.json in {run_dir}")
        return 1
    task = json.loads(task_path.read_text(encoding="utf-8"))
    defaults = build_parser().parse_args([])
    args = argparse.Namespace(
        keyword=task.get("keyword") or task.get("query") or run_dir.name,
        max_papers=int(task.get("max_papers") or defaults.max_papers),
        since_year=task.get("since_year") or defaults.since_year,
        output_dir=run_dir,
        openai_model=defaults.openai_model,
        openai_api_key_file=defaults.openai_api_key_file,
        unpaywall_email=defaults.unpaywall_email,
        github_filter=task.get("github_filter") or defaults.github_filter,
        auto_confirm=True,
        no_download=bool(task.get("no_download", defaults.no_download)),
        pdf_limit=defaults.pdf_limit,
        github_search_limit=int(task.get("github_search_limit") or defaults.github_search_limit),
        seed_search_terms=None,
        mode=task.get("mode") or defaults.mode,
        interaction=task.get("interaction") or defaults.interaction,
        quality=task.get("quality") or defaults.quality,
        include_adjacent=bool(task.get("include_adjacent", defaults.include_adjacent)),
        user_corpus=task.get("user_corpus") or [],
        sources=task.get("sources") or defaults.sources,
        enable_source=task.get("enable_source") or [],
        disable_source=task.get("disable_source") or [],
    )
    return run_agent(args)


def run_agent(args: argparse.Namespace) -> int:
    client = client_from_args(args)
    if not client.available:
        print("还没有可用的 LLM 配置。请先运行 `PaperPilot` 按提示配置，或使用 `PaperPilot config set/import`。")
        print("PaperPilot 依赖 LLM 完成需求解析和报告生成；配置完成后再继续会更稳妥。")
        return 1
    return run_v1_workflow(args, client)


def interactive_main(defaults: argparse.Namespace) -> int:
    if not ensure_llm_configured():
        return 1
    client = client_from_args(defaults)
    print("PaperPilot - AI 文献检索 Agent")
    print(f"当前模型 / Active model: {active_model_label()}")
    print("输入你的调研需求。示例：调研RNA逆折叠 序列设计 近五年的文献，要求有代码仓库的")
    print("输入 /model 管理模型，exit 或 quit 退出。\n")
    while True:
        try:
            text = input("PaperPilot> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text.lower() in {"exit", "quit", "q"}:
            return 0
        if text == "/model":
            model_menu()
            client = client_from_args(defaults)
            print(f"当前模型 / Active model: {active_model_label()}")
            continue
        print("正在解析需求并生成多样化检索关键词...", flush=True)
        intent = parse_research_intent_with_llm(text, client)
        action = confirm_intent(intent)
        if action == "run":
            args = namespace_from_intent(intent, defaults)
            return run_agent(args)
        if action == "restart":
            continue
        return 0


def confirm_intent(intent: ParsedIntent) -> str:
    while True:
        print("\n我理解你的需求如下：")
        print(f"  研究主题 / Keyword: {intent.keyword}")
        print(f"  起始年份 / Since year: {intent.since_year}")
        print(f"  论文数量 / Max papers: {intent.max_papers}")
        print(f"  代码筛选 / Code filter: {intent.github_filter}")
        print(f"  PDF 下载 / PDF download: {'skip' if intent.no_download else 'enabled'}")
        print("  多样化检索关键词 / Search terms:")
        for idx, term in enumerate(intent.search_terms[:12], start=1):
            print(f"    {idx}. {term}")
        if intent.notes:
            print("  解析依据 / Notes:")
            for note in intent.notes:
                print(f"    - {note}")
        print("\n请选择：")
        print("  1. 开始检索 / Start")
        print("  2. 修改研究主题 / Edit keyword")
        print("  3. 修改起始年份 / Edit since year")
        print("  4. 修改代码筛选 / Edit code filter")
        print("  5. 修改论文数量 / Edit max papers")
        print("  6. 切换 PDF 下载 / Toggle PDF download")
        print("  7. 修改检索关键词 / Edit search terms")
        print("  8. 重新输入需求 / Restart")
        print("  0. 退出 / Exit")
        choice = input("选择 / Choice [1]: ").strip() or "1"
        if choice == "1":
            return "run"
        if choice == "2":
            value = input("新的研究主题 / New keyword: ").strip()
            if value:
                intent.keyword = value
            continue
        if choice == "3":
            value = input("新的起始年份，例如 2021 / New since year: ").strip()
            if value.isdigit():
                intent.since_year = int(value)
            continue
        if choice == "4":
            value = input("代码筛选 any|required|none / Code filter: ").strip().lower()
            if value in {"any", "required", "none"}:
                intent.github_filter = value
            continue
        if choice == "5":
            value = input("论文数量 / Max papers: ").strip()
            if value.isdigit() and int(value) > 0:
                intent.max_papers = int(value)
            continue
        if choice == "6":
            intent.no_download = not intent.no_download
            continue
        if choice == "7":
            value = input("新的检索关键词，用分号分隔 / New search terms separated by semicolons: ").strip()
            if value:
                intent.search_terms = [item.strip() for item in value.replace("\n", ";").split(";") if item.strip()]
            continue
        if choice == "8":
            return "restart"
        if choice == "0":
            return "exit"


def namespace_from_intent(intent: ParsedIntent, defaults: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        keyword=intent.keyword,
        max_papers=intent.max_papers,
        since_year=intent.since_year,
        output_dir=None,
        openai_model=defaults.openai_model,
        openai_api_key_file=defaults.openai_api_key_file,
        unpaywall_email=defaults.unpaywall_email,
        github_filter=intent.github_filter,
        auto_confirm=intent.auto_confirm,
        no_download=intent.no_download,
        pdf_limit=defaults.pdf_limit,
        github_search_limit=defaults.github_search_limit,
        seed_search_terms=intent.search_terms,
        mode=defaults.mode,
        interaction=defaults.interaction,
        quality=defaults.quality,
        include_adjacent=defaults.include_adjacent,
        user_corpus=defaults.user_corpus,
        sources=defaults.sources,
        enable_source=defaults.enable_source,
        disable_source=defaults.disable_source,
    )


def client_from_args(args: argparse.Namespace) -> OpenAIClient:
    user_config = load_user_config()
    file_config = read_api_config(args.openai_api_key_file)
    api_key = os.getenv("OPENAI_API_KEY") or user_config.api_key or file_config.api_key
    base_url = os.getenv("OPENAI_BASE_URL") or user_config.base_url or file_config.base_url
    model = os.getenv("OPENAI_MODEL") or user_config.model or file_config.model or args.openai_model
    return OpenAIClient(api_key=api_key, model=model, base_url=base_url)


def ensure_llm_configured() -> bool:
    if os.getenv("OPENAI_API_KEY") or load_user_config().api_key:
        return True
    print("未检测到可用的 LLM 配置。")
    print("PaperPilot 需要先连接一个 LLM，用于理解需求、扩展检索关键词和生成报告。")
    answer = input("现在配置吗？[Y/n] ").strip().lower()
    if answer in {"n", "no"}:
        print("已取消配置。你可以稍后运行 `PaperPilot config set` 或 `PaperPilot config import <文件>` 后再使用。")
        return False
    return first_time_config_wizard()


def first_time_config_wizard() -> bool:
    print("\n请选择配置方式：")
    print("  1. 手动输入 / Manual input")
    print("  2. 导入本地 JSON 文件 / Import local JSON file")
    choice = input("选择 / Choice [1]: ").strip() or "1"
    if choice == "2":
        path = input("本地文件路径 / Local file path: ").strip()
        if not path:
            print("未提供文件路径，配置已取消。")
            return False
        return config_import(Path(path).expanduser(), name=None, skip_test=False) == 0
    profile = prompt_profile("default")
    if not test_llm_config(profile):
        print("配置测试失败，未保存。请检查 API Key、Base URL 和模型名。")
        return False
    config = load_app_config()
    config.profiles["default"] = profile
    config.active = "default"
    save_app_config(config)
    print("配置已保存。")
    return True


def model_menu() -> None:
    while True:
        print("\n/model 模型管理")
        print_profiles(load_app_config())
        print("\n请选择：")
        print("  1. 新增或更新模型 / Add or update")
        print("  2. 切换模型 / Switch")
        print("  3. 删除模型 / Delete")
        print("  4. 导入本地文件 / Import local file")
        print("  5. 测试当前模型 / Test active")
        print("  0. 返回 / Back")
        choice = input("选择 / Choice [0]: ").strip() or "0"
        if choice == "0":
            return
        if choice == "1":
            name = input("配置名称 / Profile name [default]: ").strip() or "default"
            current = load_app_config().profiles.get(name)
            profile = prompt_profile(name, current=current)
            if test_llm_config(profile):
                config = load_app_config()
                config.profiles[name] = profile
                config.active = name
                save_app_config(config)
                print(f"已保存并切换到模型配置：{name}")
            else:
                print("测试失败，未保存。")
            continue
        if choice == "2":
            name = input("要切换到哪个配置 / Profile name: ").strip()
            if name:
                config_use(name)
            continue
        if choice == "3":
            name = input("要删除哪个配置 / Profile name: ").strip()
            if name:
                config_delete(name)
            continue
        if choice == "4":
            path = input("本地 JSON 文件路径 / Local JSON file path: ").strip()
            name = input("配置名称，留空用文件名 / Profile name, empty for filename: ").strip() or None
            if path:
                config_import(Path(path).expanduser(), name=name, skip_test=False)
            continue
        if choice == "5":
            test_llm_config(load_user_config())
            continue


def prompt_profile(name: str, current=None):
    from .utils import ApiConfig

    current = current or ApiConfig()
    print(f"配置模型 / Configure profile: {name}")
    base_url = input(f"Base URL [{current.base_url or 'OpenAI default'}]: ").strip() or current.base_url
    default_model = current.model or ("deepseek-chat" if base_url and "deepseek" in base_url.lower() else "gpt-5.2")
    model = input(f"Model [{default_model}]: ").strip() or default_model
    api_key = getpass.getpass("API Key，留空则保留当前值 / leave empty to keep current: ").strip() or current.api_key
    return ApiConfig(api_key=api_key, base_url=base_url, model=model)


def active_model_label() -> str:
    app_config = load_app_config()
    if not app_config.active:
        return "未配置"
    profile = app_config.profiles.get(app_config.active)
    if not profile:
        return "未配置"
    model = profile.model or "(default)"
    base = profile.base_url or "OpenAI"
    return f"{app_config.active} | {model} | {base}"


def candidate_limit(max_papers: int, query_count: int, github_filter: str) -> int:
    query_count = max(1, query_count)
    if github_filter == "required":
        return max(10, min(30, (max_papers * 3) // query_count))
    return max(8, min(25, (max_papers * 2) // query_count))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
