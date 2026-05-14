from __future__ import annotations

import argparse
import getpass
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .openai_client import OpenAIClient
from .sources import SourceConfig, source_config_from_dict
from .utils import ApiConfig


CONFIG_DIR = Path(os.getenv("PAPERPILOT_HOME", Path.home() / ".paperpilot"))
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class AppConfig:
    active: str | None = None
    profiles: dict[str, ApiConfig] = field(default_factory=dict)
    sources: dict[str, SourceConfig] = field(default_factory=dict)


def load_app_config(path: Path = CONFIG_PATH) -> AppConfig:
    if not path.exists():
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return AppConfig()
    if not isinstance(data, dict):
        return AppConfig()
    profiles: dict[str, ApiConfig] = {}
    raw_profiles = data.get("profiles")
    if isinstance(raw_profiles, dict):
        for name, raw in raw_profiles.items():
            if not isinstance(raw, dict):
                continue
            profiles[str(name)] = ApiConfig(
                api_key=raw.get("api_key") or None,
                base_url=raw.get("base_url") or None,
                model=raw.get("model") or None,
            )
    elif isinstance(data.get("llm"), dict):
        raw = data["llm"]
        profiles["default"] = ApiConfig(
            api_key=raw.get("api_key") or None,
            base_url=raw.get("base_url") or None,
            model=raw.get("model") or None,
        )
    active = data.get("active") if isinstance(data.get("active"), str) else None
    if not active and profiles:
        active = next(iter(profiles))
    sources: dict[str, SourceConfig] = {}
    raw_sources = data.get("sources")
    if isinstance(raw_sources, dict):
        for name, raw in raw_sources.items():
            if isinstance(raw, dict):
                sources[str(name)] = source_config_from_dict(raw)
    return AppConfig(active=active, profiles=profiles, sources=sources)


def save_app_config(config: AppConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "active": config.active or "",
        "profiles": {
            name: {
                "api_key": profile.api_key or "",
                "base_url": profile.base_url or "",
                "model": profile.model or "",
            }
            for name, profile in config.profiles.items()
        },
        "sources": {name: source.to_dict() for name, source in config.sources.items()},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_user_config(path: Path = CONFIG_PATH) -> ApiConfig:
    config = load_app_config(path)
    if config.active and config.active in config.profiles:
        return config.profiles[config.active]
    return ApiConfig()


def save_user_config(config: ApiConfig, path: Path = CONFIG_PATH) -> None:
    app_config = load_app_config(path)
    name = app_config.active or "default"
    app_config.active = name
    app_config.profiles[name] = config
    save_app_config(app_config, path)


def active_profile_name(path: Path = CONFIG_PATH) -> str | None:
    return load_app_config(path).active


def build_config_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="PaperPilot config",
        description="管理 PaperPilot 的 LLM 配置 / Manage PaperPilot LLM configuration",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set", help="保存 LLM 配置 / Save LLM configuration")
    set_parser.add_argument("--name", default=None, help="配置名称，默认 active 或 default / Profile name")
    set_parser.add_argument("--api-key", help="LLM API Key；不传则隐藏输入 / LLM API key; prompted if omitted")
    set_parser.add_argument("--base-url", default=None, help="OpenAI-compatible base URL，例如 https://api.deepseek.com")
    set_parser.add_argument("--model", default=None, help="模型名，例如 deepseek-chat 或 gpt-5.2")
    set_parser.add_argument("--skip-test", action="store_true", help="跳过连通测试 / Skip connection test")

    use_parser = subparsers.add_parser("use", help="切换 active 配置 / Switch active profile")
    use_parser.add_argument("name")

    delete_parser = subparsers.add_parser("delete", help="删除配置 / Delete a profile")
    delete_parser.add_argument("name")

    import_parser = subparsers.add_parser("import", help="从本地 JSON 文件导入配置 / Import config from a local JSON file")
    import_parser.add_argument("path", type=Path, help="本地配置文件路径 / Local config file path")
    import_parser.add_argument("--name", default=None, help="配置名称，默认使用文件中的 name 或文件名 / Profile name")
    import_parser.add_argument("--skip-test", action="store_true", help="跳过连通测试 / Skip connection test")

    subparsers.add_parser("list", help="列出所有配置 / List profiles")
    subparsers.add_parser("show", help="显示当前配置，隐藏 API Key / Show current config with masked key")
    subparsers.add_parser("path", help="显示配置文件路径 / Show config file path")
    subparsers.add_parser("clear", help="删除用户级配置 / Delete user config")
    return parser


def run_config_command(argv: list[str]) -> int:
    parser = build_config_parser()
    args = parser.parse_args(argv)
    if args.command == "set":
        return config_set(args)
    if args.command == "use":
        return config_use(args.name)
    if args.command == "delete":
        return config_delete(args.name)
    if args.command == "import":
        return config_import(args.path, name=args.name, skip_test=args.skip_test)
    if args.command == "list":
        print_profiles(load_app_config())
        return 0
    if args.command == "show":
        app_config = load_app_config()
        print(f"Config path: {CONFIG_PATH}")
        print_profiles(app_config)
        return 0
    if args.command == "path":
        print(CONFIG_PATH)
        return 0
    if args.command == "clear":
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
            print(f"Deleted config: {CONFIG_PATH}")
        else:
            print(f"No config found: {CONFIG_PATH}")
        return 0
    parser.print_help()
    return 2


def config_set(args) -> int:
    app_config = load_app_config()
    name = args.name or app_config.active or "default"
    current = app_config.profiles.get(name, ApiConfig())
    api_key = args.api_key
    if api_key is None:
        prompt = f"API Key for {name}，留空则保留当前值 / leave empty to keep current: "
        api_key = getpass.getpass(prompt).strip()
    config = ApiConfig(
        api_key=api_key or current.api_key,
        base_url=args.base_url if args.base_url is not None else current.base_url,
        model=args.model if args.model is not None else current.model,
    )
    if not args.skip_test and not test_llm_config(config):
        print("LLM config test failed. Not saved.")
        return 1
    app_config.profiles[name] = config
    app_config.active = name
    save_app_config(app_config)
    print(f"Saved active config '{name}': {CONFIG_PATH}")
    print_profile(name, config, active=True)
    return 0


def config_use(name: str) -> int:
    app_config = load_app_config()
    if name not in app_config.profiles:
        print(f"Profile not found: {name}")
        return 1
    app_config.active = name
    save_app_config(app_config)
    print(f"Active profile: {name}")
    return 0


def config_delete(name: str) -> int:
    app_config = load_app_config()
    if name not in app_config.profiles:
        print(f"Profile not found: {name}")
        return 1
    del app_config.profiles[name]
    if app_config.active == name:
        app_config.active = next(iter(app_config.profiles), None)
    save_app_config(app_config)
    print(f"Deleted profile: {name}")
    if app_config.active:
        print(f"Active profile: {app_config.active}")
    return 0


def config_import(path: Path, *, name: str | None = None, skip_test: bool = False) -> int:
    try:
        profile = read_profile_file(path)
    except (OSError, ValueError) as exc:
        print(f"Could not read config file: {exc}")
        return 1
    profile_name = name or profile.get("name") or path.stem or "default"
    config = ApiConfig(
        api_key=profile.get("api_key") or profile.get("key"),
        base_url=profile.get("base_url") or profile.get("api_base"),
        model=profile.get("model"),
    )
    if not skip_test and not test_llm_config(config):
        print("LLM config test failed. Not saved.")
        return 1
    app_config = load_app_config()
    app_config.profiles[profile_name] = config
    app_config.active = profile_name
    save_app_config(app_config)
    print(f"Imported and saved active profile '{profile_name}' to {CONFIG_PATH}")
    print("The source file is no longer needed after import.")
    print_profile(profile_name, config, active=True)
    return 0


def read_profile_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r",\s*([}\]])", r"\1", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("config file must contain a JSON object")
    if isinstance(data.get("llm"), dict):
        data = data["llm"]
    if not any(data.get(key) for key in ("api_key", "key")):
        raise ValueError("missing api_key")
    return data


def print_profiles(config: AppConfig) -> None:
    if not config.profiles:
        print("No LLM profiles configured.")
        return
    for name, profile in config.profiles.items():
        print_profile(name, profile, active=(name == config.active))


def print_profile(name: str, config: ApiConfig, *, active: bool) -> None:
    prefix = "*" if active else "-"
    print(f"{prefix} {name}")
    print(f"  base_url: {config.base_url or '(default OpenAI)'}")
    print(f"  model: {config.model or '(default)'}")
    print(f"  api_key: {mask_secret(config.api_key)}")


def test_llm_config(config: ApiConfig) -> bool:
    if not config.api_key:
        print("Missing API key.")
        return False
    try:
        client = OpenAIClient(api_key=config.api_key, model=config.model or "gpt-5.2", base_url=config.base_url)
        text = client.text(
            "You are a connection test endpoint. Reply with a short non-empty answer.",
            "Please reply with: OK",
            max_output_tokens=128,
        )
        ok = bool(text.strip())
        if ok:
            print("LLM config test passed.")
        else:
            print("LLM config test returned empty output.")
            if config.base_url and "deepseek" in config.base_url.lower():
                print("If this keeps happening, try model `deepseek-chat` or check whether the configured model name is available.")
        return ok
    except Exception as exc:
        print(f"LLM config test failed: {exc}")
        return False


def mask_secret(value: str | None) -> str:
    if not value:
        return "(not set)"
    if len(value) <= 10:
        return "*" * len(value)
    return value[:4] + "..." + value[-4:]
