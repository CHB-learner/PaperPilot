from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .sources import SOURCE_SPECS, SourceConfig, configured_api_key, resolve_enabled_sources


console = Console()


@dataclass
class SourceSummary:
    enabled_free: int
    configured_optional: int
    missing_optional: list[str]
    enabled_sources: list[str]


def source_status_summary(source_configs: dict[str, SourceConfig] | None = None, mode: str = "auto") -> SourceSummary:
    source_configs = source_configs or {}
    enabled = resolve_enabled_sources(mode, source_configs)
    enabled_set = set(enabled)
    enabled_free = sum(1 for name in enabled if not SOURCE_SPECS[name].requires_key)
    configured_optional = sum(
        1 for name, spec in SOURCE_SPECS.items() if spec.requires_key and bool(configured_api_key(name, source_configs.get(name)))
    )
    missing_optional = [
        name
        for name, spec in SOURCE_SPECS.items()
        if spec.requires_key and not configured_api_key(name, source_configs.get(name)) and name not in enabled_set
    ]
    return SourceSummary(enabled_free, configured_optional, missing_optional, enabled)


def print_welcome(app_config, active_model_label: str, *, source_mode: str = "auto") -> None:
    summary = source_status_summary(app_config.sources, source_mode)
    profile = app_config.profiles.get(app_config.active) if app_config.active else None
    env_key = os.getenv("OPENAI_API_KEY")
    env_base = os.getenv("OPENAI_BASE_URL")
    key_status = "configured" if env_key or (profile and profile.api_key) else "missing"
    base_url = env_base or (profile.base_url if profile and profile.base_url else "OpenAI default")
    subtitle = (
        "Scholarly literature review agent for search, evidence, code, PDFs, bilingual reports, and Obsidian Wiki.\n"
        "[dim]Type a research request in natural language. Use /model, /sources, /doctor, /help, or exit.[/dim]"
    )
    console.print(
        Panel.fit(
            f"[bold cyan]PaperPilot[/bold cyan] [dim]v{__version__}[/dim]\n{subtitle}",
            title="✈️  Research Copilot",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
    table.add_column("Area", style="bold")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    table.add_row("LLM", _status_text(key_status == "configured"), active_model_label)
    table.add_row("Model API", key_status, base_url)
    table.add_row("Free sources", "enabled", f"{summary.enabled_free} sources")
    table.add_row("Optional APIs", "configured", f"{summary.configured_optional} configured")
    table.add_row(
        "Missing optional",
        "info",
        ", ".join(summary.missing_optional[:6]) + (" ..." if len(summary.missing_optional) > 6 else "") or "none",
    )
    console.print(table)
    console.print("[bold]Example[/bold]: 调研CVPR/ICML近三年关于少样本学习在生物序列中的应用，要求有代码链接")
    console.print("[dim]Commands: /model  /sources  /doctor  /help  exit[/dim]\n")


def print_doctor_report(report, *, compact: bool = False) -> None:
    border = {"pass": "green", "warn": "yellow", "fail": "red"}.get(report.verdict, "cyan")
    title = f"🩺 PaperPilot Doctor: {report.verdict.upper()}"
    if compact and report.verdict == "pass":
        print_success("Doctor check passed")
        return
    table = Table(title=title, box=box.ROUNDED, header_style=f"bold {border}")
    table.add_column("Area", style="bold")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    for check in report.checks:
        table.add_row(check.area, check.name, _doctor_status(check.status), check.detail)
    console.print(table)


def print_sources_table(source_configs: dict[str, SourceConfig] | None = None, *, mode: str = "auto") -> None:
    source_configs = source_configs or {}
    enabled = set(resolve_enabled_sources(mode, source_configs))
    table = Table(title="🔎 PaperPilot Sources", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Source", style="bold")
    table.add_column("Domain")
    table.add_column("Default")
    table.add_column("API")
    table.add_column("Status")
    table.add_column("PDF")
    table.add_column("Citations")
    for name, spec in SOURCE_SPECS.items():
        cfg = source_configs.get(name)
        has_key = bool(configured_api_key(name, cfg))
        table.add_row(
            spec.display_name,
            spec.domain,
            "yes" if spec.enabled_by_default else "optional",
            "key" if spec.requires_key else "free",
            "✅ enabled" if name in enabled else ("🔑 configured" if has_key else "○ disabled"),
            spec.pdf_support,
            spec.citation_support,
        )
    console.print(table)


def print_intent_summary(intent, *, source_mode: str) -> None:
    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("Field", style="bold cyan")
    table.add_column("Value", overflow="fold")
    table.add_row("Research topic", intent.keyword)
    table.add_row("Since year", str(intent.since_year))
    table.add_row("Max papers", str(intent.max_papers))
    table.add_row("Code filter", intent.github_filter)
    table.add_row("PDF download", "skip" if intent.no_download else "enabled")
    table.add_row("Sources", source_mode)
    console.print(Panel(table, title="🧭 Parsed Research Intent", border_style="cyan", box=box.ROUNDED))

    terms = Table(title="Diversified Search Terms", box=box.SIMPLE, header_style="bold")
    terms.add_column("#", justify="right", style="cyan", width=3)
    terms.add_column("Query", overflow="fold")
    for idx, term in enumerate(intent.search_terms[:12], start=1):
        terms.add_row(str(idx), term)
    console.print(terms)

    if intent.notes:
        notes = "\n".join(f"• {note}" for note in intent.notes)
        console.print(Panel(notes, title="Notes", border_style="yellow", box=box.ROUNDED))


def print_choice_menu() -> None:
    table = Table(title="Choose Next Action", box=box.SIMPLE, show_header=False)
    table.add_column("Key", style="bold cyan", width=4)
    table.add_column("Action")
    rows = [
        ("1", "🚀 开始检索 / Start"),
        ("2", "✏️  修改研究主题 / Edit keyword"),
        ("3", "📅 修改起始年份 / Edit since year"),
        ("4", "💻 修改代码筛选 / Edit code filter"),
        ("5", "🔢 修改论文数量 / Edit max papers"),
        ("6", "📄 切换 PDF 下载 / Toggle PDF download"),
        ("7", "🔎 修改检索关键词 / Edit search terms"),
        ("8", "🌐 修改检索来源 / Edit sources preset"),
        ("9", "↩️  重新输入需求 / Restart"),
        ("0", "退出 / Exit"),
    ]
    for key, action in rows:
        table.add_row(key, action)
    console.print(table)


def stage_start(index: int, total: int, name: str, message: str) -> None:
    console.print(f"[bold cyan]{_stage_icon(name)} [{index}/{total}] {name}[/bold cyan] [dim]{message}[/dim]")


def stage_done(name: str, details: dict[str, Any] | None = None) -> None:
    if not details:
        console.print(f"[green]✓ {name} completed[/green]")
        return
    compact = " · ".join(f"{key}={value}" for key, value in details.items())
    console.print(f"[green]✓ {name} completed[/green] [dim]{compact}[/dim]")


def print_success(message: str) -> None:
    console.print(f"[green]✓[/green] {message}")


def print_warning(message: str) -> None:
    console.print(f"[yellow]⚠[/yellow] {message}")


def print_error_panel(title: str, message: str) -> None:
    console.print(Panel(message, title=f"❌ {title}", border_style="red", box=box.ROUNDED))


def _status_text(ok: bool) -> str:
    return "[green]ready[/green]" if ok else "[red]missing[/red]"


def _doctor_status(status: str) -> str:
    return {
        "pass": "[green]pass[/green]",
        "warn": "[yellow]warn[/yellow]",
        "fail": "[red]fail[/red]",
        "skip": "[dim]skip[/dim]",
    }.get(status, status)


def _stage_icon(name: str) -> str:
    return {
        "Intake": "🧭",
        "Protocol": "📋",
        "Search": "🔎",
        "Corpus": "🧱",
        "Screening": "🧪",
        "Verification": "✅",
        "Synthesis": "🧠",
        "Review": "🛡️",
        "Report": "📝",
    }.get(name, "•")
