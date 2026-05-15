from __future__ import annotations

import argparse
import getpass
import os
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SourceSpec:
    name: str
    display_name: str
    domain: str
    requires_key: bool
    enabled_by_default: bool
    presets: list[str]
    rate_limit_hint: str
    metadata_quality: str
    pdf_support: str
    citation_support: str
    key_env: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceConfig:
    enabled: bool | None = None
    api_key: str | None = None
    base_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "api_key": self.api_key or "",
            "base_url": self.base_url or "",
        }


SOURCE_SPECS: dict[str, SourceSpec] = {
    "arxiv": SourceSpec("arxiv", "arXiv", "cs", False, True, ["core", "cs"], "polite concurrent requests", "high", "high", "low"),
    "semantic_scholar": SourceSpec("semantic_scholar", "Semantic Scholar", "general", False, True, ["core", "cs", "biomed"], "public endpoint limits may apply", "high", "medium", "high"),
    "openalex": SourceSpec("openalex", "OpenAlex", "general", False, True, ["core", "cs", "biomed"], "polite public API", "high", "medium", "high"),
    "crossref": SourceSpec("crossref", "Crossref", "general", False, True, ["core", "cs", "biomed"], "polite public API", "medium", "low", "medium"),
    "openreview": SourceSpec("openreview", "OpenReview", "cs", False, True, ["core", "cs"], "public endpoint limits may apply", "high", "high", "low"),
    "pubmed": SourceSpec("pubmed", "PubMed / NCBI E-utilities", "biomed", False, True, ["core", "biomed"], "NCBI public E-utilities", "high", "low", "medium"),
    "europe_pmc": SourceSpec("europe_pmc", "Europe PMC", "biomed", False, True, ["core", "biomed"], "public REST API", "high", "high", "medium"),
    "biorxiv": SourceSpec("biorxiv", "bioRxiv", "biomed", False, True, ["biomed"], "date-window API filtered locally", "medium", "high", "low"),
    "medrxiv": SourceSpec("medrxiv", "medRxiv", "biomed", False, True, ["biomed"], "date-window API filtered locally", "medium", "high", "low"),
    "dblp": SourceSpec("dblp", "DBLP", "cs", False, True, ["core", "cs"], "public API", "high", "low", "low"),
    "acl_anthology": SourceSpec("acl_anthology", "ACL Anthology", "cs", False, True, ["cs"], "public website search", "medium", "medium", "low"),
    "core": SourceSpec("core", "CORE", "general", True, False, ["configured"], "API key required", "high", "high", "medium", "CORE_API_KEY"),
    "lens": SourceSpec("lens", "Lens.org Scholarly API", "general", True, False, ["configured"], "API key required", "high", "medium", "high", "LENS_API_KEY"),
    "ieee": SourceSpec("ieee", "IEEE Xplore", "cs", True, False, ["configured", "cs"], "API key required", "high", "low", "medium", "IEEE_API_KEY"),
    "springer": SourceSpec("springer", "Springer Nature", "general", True, False, ["configured"], "API key required", "high", "medium", "medium", "SPRINGER_API_KEY"),
    "elsevier": SourceSpec("elsevier", "Elsevier / Scopus", "general", True, False, ["configured"], "API key required", "high", "low", "high", "ELSEVIER_API_KEY"),
    "dimensions": SourceSpec("dimensions", "Dimensions", "general", True, False, ["configured"], "API key required", "high", "low", "high", "DIMENSIONS_API_KEY"),
    "deepxiv": SourceSpec("deepxiv", "DeepXiv / Agentic Data", "general", True, False, ["configured", "core", "cs", "biomed"], "API token required; 10,000 free daily requests after registration", "high", "high", "medium", "DEEPXIV_TOKEN"),
}


def source_config_from_dict(raw: dict[str, Any] | None) -> SourceConfig:
    raw = raw or {}
    enabled = raw.get("enabled")
    if enabled not in {True, False, None}:
        enabled = None
    return SourceConfig(
        enabled=enabled,
        api_key=raw.get("api_key") or raw.get("key") or None,
        base_url=raw.get("base_url") or None,
    )


def configured_api_key(source: str, config: SourceConfig | None = None) -> str | None:
    spec = SOURCE_SPECS[source]
    env_key = os.getenv(f"PAPERPILOT_{source.upper()}_API_KEY") or (os.getenv(spec.key_env) if spec.key_env else None)
    return env_key or (config.api_key if config else None)


def resolve_enabled_sources(
    mode: str = "auto",
    source_configs: dict[str, SourceConfig] | None = None,
    enable_sources: list[str] | None = None,
    disable_sources: list[str] | None = None,
) -> list[str]:
    source_configs = source_configs or {}
    enable = {_normalize_source_name(name) for name in enable_sources or [] if name}
    disable = {_normalize_source_name(name) for name in disable_sources or [] if name}
    names: list[str] = []
    for name, spec in SOURCE_SPECS.items():
        cfg = source_configs.get(name)
        if name in disable or (cfg and cfg.enabled is False):
            continue
        active = False
        if mode == "all":
            active = not spec.requires_key or bool(configured_api_key(name, cfg))
        elif mode == "configured":
            active = bool(configured_api_key(name, cfg)) or (cfg and cfg.enabled is True)
        elif mode in {"core", "biomed", "cs"}:
            active = mode in spec.presets and (not spec.requires_key or bool(configured_api_key(name, cfg)) or (cfg and cfg.enabled is True))
        else:
            active = spec.enabled_by_default or bool(configured_api_key(name, cfg)) or (cfg and cfg.enabled is True)
        if name in enable:
            active = not spec.requires_key or bool(configured_api_key(name, cfg)) or (cfg and cfg.enabled is True)
        if active:
            names.append(name)
    return names


def source_manifest(source_configs: dict[str, SourceConfig] | None = None) -> list[dict[str, Any]]:
    source_configs = source_configs or {}
    payload = []
    for name, spec in SOURCE_SPECS.items():
        cfg = source_configs.get(name)
        item = spec.to_dict()
        item["configured"] = bool(configured_api_key(name, cfg))
        item["user_enabled"] = cfg.enabled if cfg else None
        payload.append(item)
    return payload


def build_sources_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="PaperPilot sources", description="管理论文检索来源 / Manage paper search sources")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="列出来源 / List sources")
    enable = subparsers.add_parser("enable", help="启用来源 / Enable source")
    enable.add_argument("source")
    disable = subparsers.add_parser("disable", help="禁用来源 / Disable source")
    disable.add_argument("source")
    config = subparsers.add_parser("config", help="配置需要 API key 的来源 / Configure source API key")
    config.add_argument("source")
    config.add_argument("--api-key", default=None)
    config.add_argument("--base-url", default=None)
    test = subparsers.add_parser("test", help="测试来源配置 / Test source")
    test.add_argument("source")
    return parser


def run_sources_command(argv: list[str]) -> int:
    from .config import ensure_config_initialized, load_app_config, save_app_config
    from .searchers import search_one_source

    parser = build_sources_parser()
    args = parser.parse_args(argv)
    ensure_config_initialized()
    app_config = load_app_config()
    if args.command == "list":
        print_sources(app_config.sources)
        return 0
    source = _normalize_source_name(getattr(args, "source", ""))
    if source not in SOURCE_SPECS:
        print(f"Unknown source: {source}")
        return 1
    cfg = app_config.sources.get(source, SourceConfig())
    if args.command == "enable":
        cfg.enabled = True
        app_config.sources[source] = cfg
        save_app_config(app_config)
        print(f"Enabled source: {source}")
        return 0
    if args.command == "disable":
        cfg.enabled = False
        app_config.sources[source] = cfg
        save_app_config(app_config)
        print(f"Disabled source: {source}")
        return 0
    if args.command == "config":
        api_key = args.api_key
        if SOURCE_SPECS[source].requires_key and api_key is None:
            api_key = getpass.getpass(f"API key for {source}, leave empty to keep current: ").strip()
        cfg.api_key = api_key or cfg.api_key
        cfg.base_url = args.base_url or cfg.base_url
        cfg.enabled = True
        app_config.sources[source] = cfg
        save_app_config(app_config)
        print(f"Saved source config: {source}")
        return 0
    if args.command == "test":
        if SOURCE_SPECS[source].requires_key and not configured_api_key(source, cfg):
            print(f"Missing API key for source: {source}")
            return 1
        papers = search_one_source(source, "RNA", limit=1, since_year=None, source_config=cfg)
        print(f"{source}: ok, returned {len(papers)} paper(s)")
        return 0
    parser.print_help()
    return 2


def print_sources(source_configs: dict[str, SourceConfig] | None = None) -> None:
    enabled_auto = set(resolve_enabled_sources("auto", source_configs or {}))
    print("PaperPilot sources:")
    for name, spec in SOURCE_SPECS.items():
        cfg = (source_configs or {}).get(name)
        configured = "configured" if configured_api_key(name, cfg) else "no-key"
        status = "enabled" if name in enabled_auto else "disabled"
        key = "requires-key" if spec.requires_key else "free"
        print(f"- {name:17} {status:8} {key:12} {configured:10} {spec.display_name}")


def _normalize_source_name(name: str) -> str:
    return name.strip().lower().replace("-", "_")
