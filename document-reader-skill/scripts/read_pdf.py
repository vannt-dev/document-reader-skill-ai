#!/usr/bin/env python3
"""Read a PDF's page outline, the text of a bounded page range, or its tables.

A page without a text layer (a scan) is read with OCR when --ocr is given.
"""

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
    result = {
        "document": str(path), "type": "pdf", "page_count": page_count,
        "pages": pages,
        "pages_without_text": [page["page"] for page in pages if page["chars"] == 0],
        "bookmarks": bookmarks, "bookmarks_truncated": truncated,
    }
    if result["pages_without_text"]:
        import ocr

        # Whether reading those pages again with --ocr can work on this machine.
        result["ocr_available"] = ocr.available()
    return result


def read(
    path: Path, pages: str | None, max_chars: int,
    use_ocr: bool = False, ocr_lang: str | None = None, ocr_dpi: int | None = None,
) -> dict:
    reader = open_pdf(path)
    start, end = parse_pages(pages, len(reader.pages))
    texts = {number: pdf_page_text(reader, number) for number in range(start, end + 1)}
    recognised: dict[int, str] = {}
    info = None
    if use_ocr:
        import ocr

        scanned = [number for number, text in texts.items() if not text]
        if scanned:
            languages = ocr.resolve_languages(ocr_lang)
            recognised = ocr.pdf_pages_text(path, scanned, languages, ocr_dpi or ocr.DEFAULT_DPI)
            info = ocr.describe(languages, [number for number in scanned if recognised.get(number)])
    parts, empty = [], []
    for number, text in texts.items():
        if text:
            parts.append(f"--- page {number} ---\n{text}")
        elif recognised.get(number):
            # Marked, so a reader knows this text was recognised from a picture
            # and may hold misread characters.
            parts.append(f"--- page {number} (OCR) ---\n{recognised[number]}")
        else:
            empty.append(number)
    content = "\n\n".join(parts)
    result = {
        "document": str(path), "type": "pdf",
        "source": {"start_page": start, "end_page": end},
        "content": content[:max_chars], "truncated": len(content) > max_chars,
        "pages_without_text": empty,
    }
    if info is not None:
        result["ocr"] = info
    return result


def tables(path: Path, pages: str | None, max_rows: int) -> dict:
    """Tables on the selected pages, each capped at `max_rows` rows."""
    from pdf_tables import extract_tables

    start, end = parse_pages(pages, len(open_pdf(path).pages))
    found, truncated = [], False
    for table in extract_tables(path, start, end):
        rows = table["rows"]
        truncated = truncated or len(rows) > max_rows
        found.append({
            "page": table["page"], "table": table["table"],
            "rows": len(rows), "columns": max(len(row) for row in rows),
            "cells": rows[:max_rows],
        })
    return {
        "document": str(path), "type": "pdf",
        "source": {"start_page": start, "end_page": end},
        "tables": found, "truncated": truncated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document")
    parser.add_argument("--outline-only", action="store_true")
    parser.add_argument("--pages", help="One page (3) or an inclusive range (3-5)")
    parser.add_argument("--tables", action="store_true", help="Return the tables on the pages instead of their text")
    parser.add_argument("--max-rows", type=int, default=100, help="Row limit per table, with --tables")
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--ocr", action="store_true", help="Read pages that have no text layer with Tesseract")
    parser.add_argument("--ocr-lang", help="Languages for --ocr, such as vie+eng (default: Vietnamese and English)")
    parser.add_argument("--ocr-dpi", type=int, help="Resolution a page is rendered at for --ocr (default: 300)")
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        path = require_path(args.document, {".pdf"})
        if args.max_chars < 1 or args.max_rows < 1:
            raise ValueError("max-chars and max-rows must be positive")
        if args.ocr_dpi is not None and not 72 <= args.ocr_dpi <= 600:
            raise ValueError("ocr-dpi must be between 72 and 600")
        if args.outline_only:
            emit(outline(path), args.output)
        elif args.tables:
            emit(tables(path, args.pages, args.max_rows), args.output)
        else:
            emit(read(path, args.pages, args.max_chars, args.ocr, args.ocr_lang, args.ocr_dpi), args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
