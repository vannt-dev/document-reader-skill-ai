#!/usr/bin/env python3
"""Read a Markdown outline, heading section, or bounded line range."""

from __future__ import annotations

import argparse
import re
import sys

from common import add_output_argument, emit, require_path

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def outline(lines: list[str]) -> list[dict]:
    result = []
    fenced = False
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            fenced = not fenced
        if not fenced and (match := HEADING.match(line)):
            result.append({"level": len(match.group(1)), "title": match.group(2).rstrip("# "), "line": number})
    return result


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
        path = require_path(args.document, {".md", ".markdown"})
        if args.max_chars < 1:
            raise ValueError("max-chars must be positive")
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        headings = outline(lines)
        if args.outline_only:
            emit({"document": str(path), "type": "markdown", "line_count": len(lines), "outline": headings}, args.output)
            return 0
        start = max(1, args.start_line or 1)
        end = min(len(lines), args.end_line or len(lines))
        selected_heading = None
        if args.heading:
            candidates = [item for item in headings if item["title"].casefold() == args.heading.casefold()]
            if not candidates:
                raise ValueError(f"Heading not found: {args.heading!r}")
            selected_heading = candidates[0]
            start = selected_heading["line"]
            end = len(lines)
            for item in headings:
                if item["line"] > start and item["level"] <= selected_heading["level"]:
                    end = item["line"] - 1
                    break
        text = "\n".join(lines[start - 1:end])
        truncated = len(text) > args.max_chars
        text = text[:args.max_chars]
        emit({
            "document": str(path), "type": "markdown",
            "source": {"heading": selected_heading, "start_line": start, "end_line": end},
            "content": text, "truncated": truncated,
        }, args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

