#!/usr/bin/env python3
"""Read a PDF's page outline or the text of a bounded page range."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import add_output_argument, emit, require_path
from doc_text import open_pdf, pdf_bookmarks, pdf_page_text


def parse_pages(raw: str | None, page_count: int) -> tuple[int, int]:
    """Turn "3" or "3-5" into an inclusive 1-based range inside the document."""
    if not raw:
        return 1, page_count
    first, _, last = raw.partition("-")
    try:
        start = int(first)
        end = int(last) if last else start
    except ValueError as exc:
        raise ValueError(f"pages must look like 3 or 3-5, not {raw!r}") from exc
    if start < 1 or end < start:
        raise ValueError(f"Invalid page range: {raw!r}")
    if start > page_count:
        raise ValueError(f"Page {start} is past the end of the document ({page_count} pages)")
    return start, min(end, page_count)


def outline(path: Path, max_bookmarks: int = 200) -> dict:
    reader = open_pdf(path)
    page_count = len(reader.pages)
    pages = [{"page": number, "chars": len(pdf_page_text(reader, number))} for number in range(1, page_count + 1)]
    bookmarks, truncated = pdf_bookmarks(reader, max_bookmarks)
    return {
        "document": str(path), "type": "pdf", "page_count": page_count,
        "pages": pages,
        "pages_without_text": [page["page"] for page in pages if page["chars"] == 0],
        "bookmarks": bookmarks, "bookmarks_truncated": truncated,
    }


def read(path: Path, pages: str | None, max_chars: int) -> dict:
    reader = open_pdf(path)
    start, end = parse_pages(pages, len(reader.pages))
    parts, empty = [], []
    for number in range(start, end + 1):
        text = pdf_page_text(reader, number)
        if text:
            parts.append(f"--- page {number} ---\n{text}")
        else:
            empty.append(number)
    content = "\n\n".join(parts)
    return {
        "document": str(path), "type": "pdf",
        "source": {"start_page": start, "end_page": end},
        "content": content[:max_chars], "truncated": len(content) > max_chars,
        "pages_without_text": empty,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document")
    parser.add_argument("--outline-only", action="store_true")
    parser.add_argument("--pages", help="One page (3) or an inclusive range (3-5)")
    parser.add_argument("--max-chars", type=int, default=12000)
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        path = require_path(args.document, {".pdf"})
        if args.max_chars < 1:
            raise ValueError("max-chars must be positive")
        emit(outline(path) if args.outline_only else read(path, args.pages, args.max_chars), args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
