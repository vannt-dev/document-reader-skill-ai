"""Pure helpers for building and querying the document cache. No openpyxl."""

from __future__ import annotations

import re

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def doc_id_for(relative_path: str) -> str:
    normalized = relative_path.strip().replace("\\", "/").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug or "doc"


def column_letter(index: int) -> str:
    if index < 1:
        raise ValueError("column index must be >= 1")
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def excel_block_ranges(max_row: int, window: int) -> list[tuple[int, int]]:
    if window < 1:
        raise ValueError("window must be >= 1")
    if max_row < 1:
        return []
    ranges = []
    start = 1
    while start <= max_row:
        end = min(start + window - 1, max_row)
        ranges.append((start, end))
        start = end + 1
    return ranges


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "section"


def markdown_headings(lines: list[str]) -> list[dict]:
    result = []
    fenced = False
    for number, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fenced = not fenced
        if not fenced and (match := HEADING.match(line)):
            result.append({
                "level": len(match.group(1)),
                "title": match.group(2).rstrip("# "),
                "line": number,
            })
    return result


def markdown_sections(lines: list[str]) -> list[dict]:
    headings = markdown_headings(lines)
    sections = []
    first = headings[0]["line"] if headings else len(lines) + 1
    if first > 1 and any(line.strip() for line in lines[: first - 1]):
        sections.append({"title": None, "level": 0, "start": 1, "end": first - 1})
    for index, heading in enumerate(headings):
        start = heading["line"]
        end = headings[index + 1]["line"] - 1 if index + 1 < len(headings) else len(lines)
        sections.append({
            "title": heading["title"],
            "level": heading["level"],
            "start": start,
            "end": end,
        })
    return sections
