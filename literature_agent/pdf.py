from __future__ import annotations

import re
import urllib.error
import urllib.request
from pathlib import Path

from .models import Paper
from .utils import USER_AGENT, request_json, safe_fetch, slugify, write_json


def enrich_unpaywall(papers: list[Paper], email: str | None) -> None:
    if not email:
        return
    for paper in papers:
        if paper.pdf_url or not paper.doi:
            continue
        url = f"https://api.unpaywall.org/v2/{paper.doi}?email={email}"
        data = safe_fetch(lambda: request_json(url, timeout=20), {})
        best = data.get("best_oa_location") if isinstance(data, dict) else None
        pdf_url = (best or {}).get("url_for_pdf")
        if pdf_url:
            paper.pdf_url = pdf_url


def download_pdfs(papers: list[Paper], pdf_dir: Path, limit: int | None = None) -> list[dict]:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    logs: list[dict] = []
    count = 0
    for index, paper in enumerate(papers, start=1):
        if limit is not None and count >= limit:
            logs.append({"title": paper.title, "status": "skipped", "reason": "download limit reached"})
            continue
        if not paper.pdf_url:
            logs.append({"title": paper.title, "status": "skipped", "reason": "no open pdf url"})
            continue
        if not _looks_open_pdf(paper.pdf_url):
            logs.append({"title": paper.title, "status": "skipped", "reason": "pdf url not recognized as open", "url": paper.pdf_url})
            continue
        filename = f"{index:03d}-{slugify(paper.title, 70)}.pdf"
        path = pdf_dir / filename
        try:
            req = urllib.request.Request(paper.pdf_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=45) as resp:
                content_type = resp.headers.get("Content-Type", "")
                data = resp.read()
            if b"%PDF" not in data[:1024] and "pdf" not in content_type.lower():
                logs.append({"title": paper.title, "status": "failed", "reason": "response was not a pdf", "url": paper.pdf_url})
                continue
            path.write_bytes(data)
            count += 1
            logs.append({"title": paper.title, "status": "downloaded", "path": str(path), "url": paper.pdf_url})
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logs.append({"title": paper.title, "status": "failed", "reason": str(exc), "url": paper.pdf_url})
    return logs


def extract_downloaded_fulltext(
    download_log: list[dict],
    output_dir: Path,
    *,
    fulltext_dir: Path | None = None,
    notes_path: Path | None = None,
) -> list[dict]:
    fulltext_dir = fulltext_dir or output_dir / "fulltext"
    fulltext_dir.mkdir(parents=True, exist_ok=True)
    notes: list[dict] = []
    for item in download_log:
        if item.get("status") != "downloaded" or not item.get("path"):
            notes.append(
                {
                    "title": item.get("title"),
                    "status": "not_extracted",
                    "reason": item.get("reason") or item.get("status"),
                }
            )
            continue
        pdf_path = Path(str(item["path"]))
        text_path = fulltext_dir / f"{slugify(str(item.get('title') or pdf_path.stem), 80)}.txt"
        try:
            text = extract_pdf_text(pdf_path)
            text_path.write_text(text, encoding="utf-8")
            notes.append(
                {
                    "title": item.get("title"),
                    "status": "extracted",
                    "path": str(text_path),
                    "characters": len(text),
                }
            )
        except Exception as exc:
            notes.append(
                {
                    "title": item.get("title"),
                    "status": "failed",
                    "reason": str(exc),
                    "pdf_path": str(pdf_path),
                }
            )
    write_json(notes_path or output_dir / "paper_notes.json", notes)
    return notes


def attach_fulltext_paths(papers: list[Paper], notes: list[dict]) -> None:
    by_title = {str(note.get("title")): note for note in notes if note.get("status") == "extracted"}
    for paper in papers:
        note = by_title.get(paper.title)
        if note and note.get("path"):
            paper.raw["fulltext_path"] = note["path"]


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF text extraction") from exc
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages[:80]:
        parts.append(page.extract_text() or "")
    return "\n\n".join(part for part in parts if part.strip())


def _looks_open_pdf(url: str) -> bool:
    lowered = url.lower()
    return bool(
        lowered.endswith(".pdf")
        or "arxiv.org/pdf/" in lowered
        or "openreview.net/pdf" in lowered
        or re.search(r"/pdf(?:\?|$)", lowered)
    )
