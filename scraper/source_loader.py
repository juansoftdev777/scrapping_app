from __future__ import annotations

import re
from pathlib import Path

from docx import Document

from scraper.models import SourceSite

URL_RE = re.compile(r"^https?://", re.IGNORECASE)
TYPE_RE = re.compile(r"^Type\s+[A-Z]", re.IGNORECASE)


def _normalize_lines(docx_path: Path) -> list[str]:
    doc = Document(str(docx_path))
    lines: list[str] = []
    for paragraph in doc.paragraphs:
        value = paragraph.text.strip()
        if value:
            lines.append(value)
    return lines


def load_sources_from_docx(docx_path: str | Path) -> list[SourceSite]:
    path = Path(docx_path)
    if not path.exists():
        return []

    lines = _normalize_lines(path)
    sources: list[SourceSite] = []
    current_type = "Uncategorized"
    current_source: SourceSite | None = None

    for line in lines:
        if TYPE_RE.match(line):
            current_type = line.replace("(Continued)", "").strip()
            current_source = None
            continue

        if line.lower() in {"continued", "type c (continued)"}:
            continue

        if URL_RE.match(line):
            if current_source is None:
                continue
            if not current_source.listing_url:
                current_source.listing_url = line
            else:
                current_source.sample_urls.append(line)
            continue

        current_source = SourceSite(
            category=current_type,
            venue_name=line,
            listing_url="",
            sample_urls=[],
        )
        sources.append(current_source)

    return [source for source in sources if source.listing_url]
