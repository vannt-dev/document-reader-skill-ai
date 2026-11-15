#!/usr/bin/env python3
"""Read a Word (.docx) outline, heading section, or bounded paragraph range."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import add_output_argument, emit, require_path
from doc_text import (
    NO_COMMENT_STATE, docx_annotations, docx_has_comment_state, docx_items, docx_outline, docx_render,
    docx_sections, docx_threads,
)


def outline(path: Path) -> dict:
    items = docx_items(path)
    result = {
        "document": str(path), "type": "docx",
        "paragraph_count": len(items),
        "table_rows": sum(1 for item in items if item["kind"] == "table_row"),
        "outline": docx_outline(items),
    }
    # Counted only when there are any, so a plain document's outline stays as it was.
    for name, count in docx_annotations(items).items():
        result[f"{name[:-1]}_count"] = len(count)
    return result


def _select(
    path: Path, heading: str | None, start: int | None, end: int | None,
) -> tuple[list[dict], dict]:
    """The items of a heading section or paragraph range, and the `source` naming it."""
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
    return items[first - 1:last], {
        "heading": {"title": selected["title"], "level": selected["level"]} if selected else None,
        "start_paragraph": first, "end_paragraph": last,
    }


def read(
    path: Path, heading: str | None, start: int | None, end: int | None, max_chars: int,
    show_changes: bool = False,
) -> dict:
    items, source = _select(path, heading, start, end)
    text = docx_render(items, show_changes)
    return {
        "document": str(path), "type": "docx",
        "source": source,
        "content": text[:max_chars], "truncated": len(text) > max_chars,
        **docx_annotations(items),
    }


def comments(
    path: Path, heading: str | None, start: int | None, end: int | None, unresolved_only: bool = False,
) -> dict:
    """The comment threads of the whole document, a heading section or a paragraph range."""
    items, source = _select(path, heading, start, end)
    threads = docx_threads(items, unresolved_only)
    result = {"document": str(path), "type": "docx", "source": source, **threads}
    if unresolved_only:
        result["unresolved_only"] = True
    if threads["thread_count"] and not docx_has_comment_state(path):
        result["note"] = NO_COMMENT_STATE
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document")
    parser.add_argument("--outline-only", action="store_true")
    parser.add_argument("--heading", help="Case-insensitive heading title")
    parser.add_argument("--start-paragraph", type=int)
    parser.add_argument("--end-paragraph", type=int)
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument(
        "--show-changes", action="store_true",
        help="Write tracked changes into the content as {++inserted++} and {--deleted--}",
    )
    parser.add_argument(
        "--comments", action="store_true",
        help="List only the comment threads (whole document, or the heading or paragraph range), "
             "each with resolved true or false, and a count of the open ones; no content",
    )
    parser.add_argument(
        "--unresolved", action="store_true",
        help="With --comments: list only the threads that are not resolved",
    )
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        path = require_path(args.document, {".docx"})
        if args.max_chars < 1:
            raise ValueError("max-chars must be positive")
        if args.unresolved and not args.comments:
            raise ValueError(
                "--unresolved needs --comments: read_docx.py <document> --comments --unresolved"
            )
        if args.comments and (args.outline_only or args.show_changes):
            raise ValueError("--comments cannot be combined with --outline-only or --show-changes")
        if args.comments:
            emit(comments(
                path, args.heading, args.start_paragraph, args.end_paragraph, args.unresolved,
            ), args.output)
        elif args.outline_only:
            emit(outline(path), args.output)
        else:
            emit(read(
                path, args.heading, args.start_paragraph, args.end_paragraph, args.max_chars, args.show_changes,
            ), args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
