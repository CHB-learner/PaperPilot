from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig
from .openai_client import OpenAIClient
from .searchers import search_one_source
from .sources import SOURCE_SPECS, configured_api_key


@dataclass
class DoctorCheck:
    area: str
    name: str
    status: str
    detail: str


@dataclass
class DoctorReport:
    verdict: str
    checks: list[DoctorCheck]


def run_doctor(client: OpenAIClient, app_config: AppConfig, *, source_query: str = "test") -> DoctorReport:
    checks = [_check_llm(client)]
    checks.extend(_check_configured_sources(app_config, source_query=source_query))
    if any(check.status == "fail" for check in checks):
        verdict = "fail"
    elif any(check.status == "warn" for check in checks):
        verdict = "warn"
    else:
        verdict = "pass"
    return DoctorReport(verdict=verdict, checks=checks)


def _check_llm(client: OpenAIClient) -> DoctorCheck:
    if not client.available:
        return DoctorCheck("LLM", "active model", "fail", "missing API key or active profile")
    try:
        text = client.text(
            "You are a PaperPilot health check endpoint. Reply with one short non-empty answer.",
            "Reply with OK.",
            max_output_tokens=32,
        )
    except Exception as exc:
        return DoctorCheck("LLM", client.model or "active model", "fail", f"{type(exc).__name__}: {exc}")
    if not text.strip():
        return DoctorCheck("LLM", client.model or "active model", "fail", "empty model response")
    return DoctorCheck("LLM", client.model or "active model", "pass", "connection test passed")


def _check_configured_sources(app_config: AppConfig, *, source_query: str) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    configured = [
        (name, spec, app_config.sources.get(name))
        for name, spec in SOURCE_SPECS.items()
        if spec.requires_key and configured_api_key(name, app_config.sources.get(name))
    ]
    if not configured:
        return [DoctorCheck("Sources", "optional APIs", "skip", "no optional source API keys configured")]
    for name, spec, config in configured:
        try:
            papers = search_one_source(name, source_query, limit=1, since_year=None, source_config=config)
        except Exception as exc:
            checks.append(DoctorCheck("Sources", spec.display_name, "fail", f"{type(exc).__name__}: {exc}"))
            continue
        if papers:
            checks.append(DoctorCheck("Sources", spec.display_name, "pass", f"returned {len(papers)} result(s)"))
        else:
            checks.append(DoctorCheck("Sources", spec.display_name, "warn", "configured but returned 0 results for test query"))
    return checks
