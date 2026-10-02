#!/usr/bin/env python3
"""Read a Word (.docx) outline, heading section, or bounded paragraph range."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import add_output_argument, emit, require_path
from doc_text import docx_items, docx_outline, docx_render, docx_sections


def outline(path: Path) -> dict:
    items = docx_items(path)
    return {
        "document": str(path), "type": "docx",
        "paragraph_count": len(items),
        "table_rows": sum(1 for item in items if item["kind"] == "table_row"),
        "outline": docx_outline(items),
    }


def read(path: Path, heading: str | None, start: int | None, end: int | None, max_chars: int) -> dict:
    items = docx_items(path)
    first = max(1, start or 1)
    last = min(len(items), end or len(items))
    selected = None
    if heading:
        candidates = [
            section for section in docx_sections(items)
            if section["title"] and section["title"].casefold() == heading.casefold()
        ]
        if not candidates:
            raise ValueError(f"Heading not found: {heading!r}")
        selected = candidates[0]
        first = selected["start"]
        # A section ends where the next heading starts; widen it to include its sub-headings.
        last = len(items)
        for item in items[first:]:
            if item["kind"] == "heading" and item["level"] <= selected["level"]:
                last = item["index"] - 1
                break
    text = docx_render(items[first - 1:last])
    return {
        "document": str(path), "type": "docx",
        "source": {
            "heading": {"title": selected["title"], "level": selected["level"]} if selected else None,
            "start_paragraph": first, "end_paragraph": last,
        },
        "content": text[:max_chars], "truncated": len(text) > max_chars,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document")
    parser.add_argument("--outline-only", action="store_true")
    parser.add_argument("--heading", help="Case-insensitive heading title")
    parser.add_argument("--start-paragraph", type=int)
    parser.add_argument("--end-paragraph", type=int)
    parser.add_argument("--max-chars", type=int, default=12000)
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        path = require_path(args.document, {".docx"})
        if args.max_chars < 1:
            raise ValueError("max-chars must be positive")
        if args.outline_only:
            emit(outline(path), args.output)
        else:
            emit(read(path, args.heading, args.start_paragraph, args.end_paragraph, args.max_chars), args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
