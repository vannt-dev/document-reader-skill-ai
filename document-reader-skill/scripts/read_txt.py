#!/usr/bin/env python3
"""Read a plain-text file (.txt): its outline, a heading section, or a bounded line range.

The encoding is detected: a byte-order mark, UTF-8, UTF-16 without a mark, and
Windows-1252 as a fallback that always reads. Lines that look like Markdown
headings (`# Title`) are listed as the outline; a file without them is one
section.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cache_common import markdown_headings, markdown_sections
from common import add_output_argument, decode_text, emit, require_path

# A text file larger than this is refused rather than read into memory.
MAX_TEXT_BYTES = 64 * 1024 * 1024


def txt_lines(path: Path) -> tuple[list[str], str]:
    """Return (lines, encoding)."""
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise ValueError(f"Text file is larger than {MAX_TEXT_BYTES // (1024 * 1024)} MB; refusing to read it")
    text, encoding = decode_text(path.read_bytes())
    return text.splitlines(), encoding


def outline(path: Path) -> dict:
    lines, encoding = txt_lines(path)
    return {
        "document": str(path), "type": "text", "encoding": encoding,
        "line_count": len(lines), "outline": markdown_headings(lines),
    }


def read(path: Path, heading: str | None, start: int | None, end: int | None, max_chars: int) -> dict:
    lines, encoding = txt_lines(path)
    first = max(1, start or 1)
    last = min(len(lines), end or len(lines))
    selected = None
    if heading:
        headings = markdown_headings(lines)
        candidates = [item for item in headings if item["title"].casefold() == heading.casefold()]
        if not candidates:
            raise ValueError(f"Heading not found: {heading!r}")
        selected = candidates[0]
        first = selected["line"]
        last = len(lines)
        for item in headings:
            if item["line"] > first and item["level"] <= selected["level"]:
                last = item["line"] - 1
                break
    text = "\n".join(lines[first - 1:last])
    return {
        "document": str(path), "type": "text", "encoding": encoding,
        "source": {"heading": selected, "start_line": first, "end_line": last},
        "content": text[:max_chars], "truncated": len(text) > max_chars,
    }


def sections(lines: list[str], window: int) -> list[dict]:
    """Heading sections, each cut into pieces of at most `window` lines."""
    pieces = []
    for section in markdown_sections(lines):
        start = section["start"]
        while start <= section["end"]:
            end = min(start + window - 1, section["end"])
            pieces.append({**section, "start": start, "end": end})
            start = end + 1
    return pieces


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document")
    parser.add_argument("--outline-only", action="store_true")
    parser.add_argument("--heading", help="Case-insensitive heading title")
    parser.add_argument("--start-line", type=int)
    parser.add_argument("--end-line", type=int)
    parser.add_argument("--max-chars", type=int, default=12000)
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        path = require_path(args.document, {".txt"})
        if args.max_chars < 1:
            raise ValueError("max-chars must be positive")
        if args.outline_only:
            emit(outline(path), args.output)
        else:
            emit(read(path, args.heading, args.start_line, args.end_line, args.max_chars), args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
