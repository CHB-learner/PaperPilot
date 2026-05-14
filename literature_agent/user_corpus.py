from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import Paper
from .utils import compact_text


SUPPORTED_SUFFIXES = {".pdf", ".bib", ".ris", ".md", ".txt"}


def load_user_corpus(paths: list[str] | None) -> tuple[list[Paper], dict[str, Any]]:
    papers: list[Paper] = []
    log = {"version": "1.5.0", "inputs": [], "included": 0, "skipped": []}
    for raw in paths or []:
        path = Path(raw).expanduser()
        entry = {"path": str(path), "exists": path.exists()}
        log["inputs"].append(entry)
        if not path.exists():
            log["skipped"].append({"path": str(path), "reason": "path_not_found"})
            continue
        files = sorted(path.rglob("*")) if path.is_dir() else [path]
        for file in files:
            if not file.is_file() or file.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            paper = _paper_from_file(file)
            if paper:
                papers.append(paper)
            else:
                log["skipped"].append({"path": str(file), "reason": "could_not_parse_minimal_metadata"})
    log["included"] = len(papers)
    return papers, log


def _paper_from_file(path: Path) -> Paper | None:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return Paper(
            title=_title_from_filename(path),
            venue="User corpus",
            source="user_corpus",
            sources=["user_corpus"],
            raw={"path": str(path), "obtained_via": "local_pdf"},
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".bib":
        return _from_bibtex(text, path)
    if suffix == ".ris":
        return _from_ris(text, path)
    return _from_markdown(text, path)


def _from_bibtex(text: str, path: Path) -> Paper | None:
    title = _first_match(text, r"title\s*=\s*[{\"']([^}\"']+)")
    year = _int_or_none(_first_match(text, r"year\s*=\s*[{\"']?(\d{4})"))
    doi = _first_match(text, r"doi\s*=\s*[{\"']([^}\"']+)")
    url = _first_match(text, r"url\s*=\s*[{\"']([^}\"']+)")
    authors = _authors(_first_match(text, r"author\s*=\s*[{\"']([^}\"']+)"))
    if not title:
        return None
    return Paper(title=compact_text(title), authors=authors, year=year, doi=doi, url=url, venue="User corpus", source="user_corpus", sources=["user_corpus"], raw={"path": str(path), "obtained_via": "bibtex"})


def _from_ris(text: str, path: Path) -> Paper | None:
    title = _first_match(text, r"^TI\s+-\s+(.+)$") or _first_match(text, r"^T1\s+-\s+(.+)$")
    year = _int_or_none(_first_match(text, r"^PY\s+-\s+(\d{4})"))
    doi = _first_match(text, r"^DO\s+-\s+(.+)$")
    url = _first_match(text, r"^UR\s+-\s+(.+)$")
    authors = re.findall(r"^AU\s+-\s+(.+)$", text, flags=re.M)
    if not title:
        return None
    return Paper(title=compact_text(title), authors=authors, year=year, doi=doi, url=url, venue="User corpus", source="user_corpus", sources=["user_corpus"], raw={"path": str(path), "obtained_via": "ris"})


def _from_markdown(text: str, path: Path) -> Paper | None:
    title = _first_match(text, r"^#\s+(.+)$") or _title_from_filename(path)
    abstract = compact_text("\n".join(line for line in text.splitlines() if not line.startswith("#")))[:1800]
    return Paper(title=title, abstract=abstract, venue="User corpus", source="user_corpus", sources=["user_corpus"], raw={"path": str(path), "obtained_via": "markdown"})


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.I | re.M)
    return compact_text(match.group(1)) if match else None


def _authors(value: str | None) -> list[str]:
    if not value:
        return []
    return [compact_text(item) for item in re.split(r"\s+and\s+|;", value) if compact_text(item)]


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _title_from_filename(path: Path) -> str:
    return compact_text(path.stem.replace("_", " ").replace("-", " "))
