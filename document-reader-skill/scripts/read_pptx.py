#!/usr/bin/env python3
"""Read a PowerPoint (.pptx) slide outline or the text of a bounded slide range."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import add_output_argument, emit, require_path
from doc_text import pptx_render, pptx_slides


def parse_slides(raw: str | None, last: int) -> tuple[int, int]:
    """Turn "3" or "3-5" into an inclusive 1-based range inside the deck."""
    if not raw:
        return 1, last
    first, _, end = raw.partition("-")
    try:
        start = int(first)
        stop = int(end) if end else start
    except ValueError as exc:
        raise ValueError(f"slides must look like 3 or 3-5, not {raw!r}") from exc
    if start < 1 or stop < start:
        raise ValueError(f"Invalid slide range: {raw!r}")
    if start > last:
        raise ValueError(f"Slide {start} is past the end of the deck ({last} slides)")
    return start, min(stop, last)


def outline(path: Path) -> dict:
    slides = pptx_slides(path)
    return {
        "document": str(path), "type": "pptx", "slide_count": len(slides),
        "outline": [
            {
                "slide": slide["slide"], "title": slide["title"],
                "lines": len(slide["lines"]), "has_notes": bool(slide["notes"]),
            }
            for slide in slides
        ],
    }


def read(path: Path, slides_arg: str | None, max_chars: int, include_notes: bool = True) -> dict:
    slides = pptx_slides(path)
    last = slides[-1]["slide"] if slides else 0
    if not slides:
        return {
            "document": str(path), "type": "pptx",
            "source": {"start_slide": None, "end_slide": None},
            "content": "", "truncated": False,
        }
    start, end = parse_slides(slides_arg, last)
    parts = [
        f"--- slide {slide['slide']} ---\n{pptx_render(slide, include_notes)}"
        for slide in slides
        if start <= slide["slide"] <= end
    ]
    content = "\n\n".join(parts)
    return {
        "document": str(path), "type": "pptx",
        "source": {"start_slide": start, "end_slide": end},
        "content": content[:max_chars], "truncated": len(content) > max_chars,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document")
    parser.add_argument("--outline-only", action="store_true")
    parser.add_argument("--slides", help="One slide (3) or an inclusive range (3-5)")
    parser.add_argument("--no-notes", action="store_true", help="Leave speaker notes out")
    parser.add_argument("--max-chars", type=int, default=12000)
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        path = require_path(args.document, {".pptx"})
        if args.max_chars < 1:
            raise ValueError("max-chars must be positive")
        if args.outline_only:
            emit(outline(path), args.output)
        else:
            emit(read(path, args.slides, args.max_chars, not args.no_notes), args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
