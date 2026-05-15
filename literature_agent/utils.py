from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


USER_AGENT = "paperpilot/1.3.2 (mailto:research@example.com)"


@dataclass
class ApiConfig:
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


def slugify(value: str, max_len: int = 80) -> str:
    value = re.sub(r"[^\w\s.-]+", "", value, flags=re.UNICODE).strip().lower()
    value = re.sub(r"[\s/]+", "-", value)
    return (value[:max_len] or "literature-search").strip("-")


def create_task_dir(keyword: str, runs_dir: Path = Path("runs")) -> tuple[str, Path]:
    runs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    keyword_slug = slugify(keyword, max_len=48) or "literature-search"
    for _ in range(20):
        suffix = uuid.uuid4().hex[:6]
        task_id = f"{timestamp}-{keyword_slug}-{suffix}"
        path = runs_dir / task_id
        try:
            path.mkdir(parents=False, exist_ok=False)
            return task_id, path
        except FileExistsError:
            continue
    suffix = uuid.uuid4().hex
    task_id = f"{timestamp}-{keyword_slug}-{suffix}"
    path = runs_dir / task_id
    path.mkdir(parents=False, exist_ok=False)
    return task_id, path


def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def compact_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_secret_file(path: Path | None) -> str | None:
    if not path or not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def read_api_config(path: Path | None) -> ApiConfig:
    raw = read_secret_file(path)
    if not raw:
        return ApiConfig()
    config = ApiConfig()
    lines = [line.strip() for line in raw.splitlines() if line.strip() and not line.strip().startswith("#")]
    for line in lines:
        if "=" in line:
            key, value = [part.strip() for part in line.split("=", 1)]
            key = key.lower()
            if key in {"api_key", "key", "openai_api_key", "deepseek_api_key"}:
                config.api_key = value
            elif key in {"base_url", "api_base", "openai_base_url"}:
                config.base_url = value
            elif key == "model":
                config.model = value
            continue
        if line.startswith("http://") or line.startswith("https://"):
            config.base_url = line
        elif not config.api_key:
            config.api_key = line
    if not config.api_key and lines:
        config.api_key = lines[-1]
    return config


def request_json(url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def request_text(url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str] | None = None, timeout: int = 90) -> Any:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def safe_fetch(fn, default):
    try:
        return fn()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return default


def rate_limit_pause(seconds: float = 0.25) -> None:
    time.sleep(seconds)


def stable_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def encode_query(params: dict[str, Any]) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
