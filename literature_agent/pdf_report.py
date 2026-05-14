from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def write_pdf_report(markdown_text: str, output_path: Path, *, title: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=title,
    )
    styles = _styles()
    story = [Paragraph(_escape(title), styles["Title"]), Spacer(1, 8)]
    table_buffer: list[list[str]] = []
    for raw in markdown_text.splitlines():
        line = raw.rstrip()
        if line.startswith("|"):
            row = [clean_inline_markdown(cell.strip()) for cell in line.strip("|").split("|")]
            if not _is_separator(row):
                table_buffer.append(row)
            continue
        if table_buffer:
            story.append(_table(table_buffer, styles))
            story.append(Spacer(1, 8))
            table_buffer = []
        if not line:
            story.append(Spacer(1, 5))
        elif line.startswith("# "):
            story.append(Paragraph(_escape(clean_inline_markdown(line[2:])), styles["H1"]))
        elif line.startswith("## "):
            story.append(Paragraph(_escape(clean_inline_markdown(line[3:])), styles["H2"]))
        elif line.startswith("### "):
            story.append(Paragraph(_escape(clean_inline_markdown(line[4:])), styles["H3"]))
        elif line.startswith("#### "):
            story.append(Paragraph(_escape(clean_inline_markdown(line[5:])), styles["H4"]))
        elif line.startswith("- "):
            story.append(Paragraph("&#8226; " + _escape(clean_inline_markdown(line[2:])), styles["Body"]))
        elif line == "---":
            story.append(PageBreak())
        else:
            story.append(Paragraph(_escape(clean_inline_markdown(line)), styles["Body"]))
    if table_buffer:
        story.append(_table(table_buffer, styles))
    doc.build(story)


def _styles() -> dict[str, ParagraphStyle]:
    font_name = _font_name()
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle("PaperPilotTitle", parent=base["Title"], fontName=font_name, fontSize=18, leading=22, spaceAfter=8),
        "H1": ParagraphStyle("PaperPilotH1", parent=base["Heading1"], fontName=font_name, fontSize=16, leading=20, spaceBefore=8, spaceAfter=6),
        "H2": ParagraphStyle("PaperPilotH2", parent=base["Heading2"], fontName=font_name, fontSize=13, leading=16, spaceBefore=8, spaceAfter=5),
        "H3": ParagraphStyle("PaperPilotH3", parent=base["Heading3"], fontName=font_name, fontSize=11, leading=14, spaceBefore=6, spaceAfter=4),
        "H4": ParagraphStyle("PaperPilotH4", parent=base["Heading4"], fontName=font_name, fontSize=10, leading=13, spaceBefore=4, spaceAfter=3),
        "Body": ParagraphStyle("PaperPilotBody", parent=base["BodyText"], fontName=font_name, fontSize=9.2, leading=12, spaceAfter=3),
        "Cell": ParagraphStyle("PaperPilotCell", parent=base["BodyText"], fontName=font_name, fontSize=7.2, leading=8.5),
    }


def _font_name() -> str:
    font_name = "STSong-Light"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    return font_name


def _table(rows: list[list[str]], styles: dict[str, ParagraphStyle]) -> Table:
    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]
    data = [[Paragraph(_escape(cell), styles["Cell"]) for cell in row] for row in normalized]
    available_width = A4[0] - 36 * mm
    col_width = available_width / max_cols
    table = Table(data, colWidths=[col_width] * max_cols, repeatRows=1 if len(rows) > 1 else 0)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F7")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def clean_inline_markdown(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    return text.strip()


def _is_separator(row: list[str]) -> bool:
    return bool(row) and all(set(cell) <= {"-", ":", " "} for cell in row)


def _escape(text: str) -> str:
    return html.escape(text, quote=False)
