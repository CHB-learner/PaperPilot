from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from .openai_client import OpenAIClient


CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass
class ParsedIntent:
    keyword: str
    search_terms: list[str]
    since_year: int
    max_papers: int
    github_filter: str
    no_download: bool
    auto_confirm: bool
    notes: list[str]


def parse_research_intent(text: str, *, current_year: int | None = None) -> ParsedIntent:
    current_year = current_year or dt.datetime.now().year
    raw = text.strip()
    since_year = 2021
    max_papers = 50
    github_filter = "any"
    no_download = False
    notes: list[str] = []

    years = re.findall(r"(20\d{2})", raw)
    if years:
        since_year = min(int(y) for y in years)
        notes.append(f"检测到年份，since_year={since_year}")

    recent_match = re.search(r"近\s*([0-9一二两三四五六七八九十]+)\s*年", raw)
    if recent_match:
        n = _parse_number(recent_match.group(1))
        if n:
            since_year = current_year - n
            notes.append(f"检测到近 {n} 年，since_year={since_year}")

    max_match = re.search(r"(?:最多|前|top\s*)\s*([0-9]{1,3})\s*(?:篇|papers?)?", raw, re.I)
    if max_match:
        max_papers = max(1, int(max_match.group(1)))
        notes.append(f"检测到论文数量，max_papers={max_papers}")

    lowered = raw.lower()
    if any(term in lowered for term in ["github", "代码仓库", "开源代码", "有代码", "带代码", "with code", "code repo"]):
        github_filter = "required"
        notes.append("检测到代码仓库要求，github_filter=required")
    if any(term in lowered for term in ["无代码", "没有代码", "without code"]):
        github_filter = "none"
        notes.append("检测到无代码筛选，github_filter=none")
    if any(term in lowered for term in ["不下载", "不用下载", "不要下载", "no download", "skip pdf"]):
        no_download = True
        notes.append("检测到跳过 PDF 下载，no_download=True")
    if any(term in lowered for term in ["方法不限", "不限方法", "任意方法", "方法不限制", "模型不限", "不限模型"]):
        notes.append("检测到方法不限，将不把具体方法名加入关键词")

    keyword = _clean_keyword(raw)
    return ParsedIntent(
        keyword=keyword or raw,
        search_terms=_fallback_search_terms(keyword or raw),
        since_year=since_year,
        max_papers=max_papers,
        github_filter=github_filter,
        no_download=no_download,
        auto_confirm=True,
        notes=notes,
    )


def parse_research_intent_with_llm(
    text: str,
    client: OpenAIClient | None,
    *,
    current_year: int | None = None,
) -> ParsedIntent:
    fallback = parse_research_intent(text, current_year=current_year)
    if not client or not client.available:
        return fallback
    payload = client.json(
        "You parse literature-search requests. Return only valid JSON.",
        f"""
Parse this user's research request:
{text!r}

Start from these deterministic constraints and preserve them unless the user
clearly said otherwise:
keyword={fallback.keyword!r}
since_year={fallback.since_year}
max_papers={fallback.max_papers}
github_filter={fallback.github_filter!r}
no_download={fallback.no_download}

Return JSON with:
{{
  "keyword": "clean concise research topic, not including constraints like recent years, code repository, method-unlimited",
  "search_terms": [
    "diverse English scholarly search query 1",
    "diverse English scholarly search query 2"
  ],
  "notes": ["short Chinese explanation"]
}}

Search terms requirements:
- 8 to 12 English queries.
- Include synonyms and adjacent terminology.
- Include both broad and narrow queries.
- Include code-oriented query variants if code repositories are required.
- For Chinese biological terms, translate to standard English academic terms.
""",
        fallback={"keyword": fallback.keyword, "search_terms": fallback.search_terms, "notes": []},
    )
    keyword = str(payload.get("keyword") or fallback.keyword).strip() or fallback.keyword
    search_terms = _normalize_search_terms(payload.get("search_terms"), keyword)
    notes = fallback.notes + [f"LLM 增强检索词：{len(search_terms)} 条"]
    notes.extend(str(note) for note in payload.get("notes") or [])
    return ParsedIntent(
        keyword=keyword,
        search_terms=search_terms,
        since_year=fallback.since_year,
        max_papers=fallback.max_papers,
        github_filter=fallback.github_filter,
        no_download=fallback.no_download,
        auto_confirm=fallback.auto_confirm,
        notes=notes,
    )


def _parse_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    if value == "十":
        return 10
    if value.endswith("十") and len(value) == 2:
        return CHINESE_NUMBERS.get(value[0], 0) * 10
    if "十" in value:
        left, right = value.split("十", 1)
        tens = CHINESE_NUMBERS.get(left, 1 if left == "" else 0)
        ones = CHINESE_NUMBERS.get(right, 0) if right else 0
        return tens * 10 + ones
    return CHINESE_NUMBERS.get(value)


def _clean_keyword(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^(请|帮我|麻烦)?\s*(调研|检索|查找|搜索|研究|找)\s*", "", cleaned)
    cleaned = re.sub(r"(相关)?(方向|领域)?的?文献(综述|调研)?", " ", cleaned)
    cleaned = re.sub(r"近\s*[0-9一二两三四五六七八九十]+\s*年(?:内|来|的)?", " ", cleaned)
    cleaned = re.sub(r"(20\d{2})\s*(?:年|以来|之后|以后|至今)?", " ", cleaned)
    cleaned = re.sub(r"(要求|需要|最好|必须)?\s*(有|带|包含)?\s*(github|GitHub|代码仓库|开源代码|有代码|带代码|with code|code repo)\s*(的|论文|文献)?", " ", cleaned)
    cleaned = re.sub(r"(无代码|没有代码|without code)\s*(的|论文|文献)?", " ", cleaned)
    cleaned = re.sub(r"(不下载|不用下载|不要下载|no download|skip pdf)\s*(pdf|PDF)?", " ", cleaned)
    cleaned = re.sub(r"(方法不限|不限方法|任意方法|方法不限制|模型不限|不限模型)", " ", cleaned)
    cleaned = re.sub(r"(最多|前|top\s*)\s*[0-9]{1,3}\s*(篇|papers?)?", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"[，。；;,.]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _fallback_search_terms(keyword: str) -> list[str]:
    return [
        keyword,
        f"{keyword} deep learning",
        f"{keyword} machine learning",
        f"{keyword} generative model",
        f"{keyword} benchmark",
        f"{keyword} github",
    ]


def _normalize_search_terms(value, keyword: str) -> list[str]:
    if isinstance(value, str):
        terms = [value]
    elif isinstance(value, list):
        terms = [str(item) for item in value]
    else:
        terms = []
    cleaned: list[str] = []
    for term in terms:
        term = re.sub(r"\s+", " ", term).strip()
        if term and term.lower() not in {item.lower() for item in cleaned}:
            cleaned.append(term)
    return cleaned[:12] or _fallback_search_terms(keyword)
