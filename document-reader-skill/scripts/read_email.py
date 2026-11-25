#!/usr/bin/env python3
"""Read an e-mail file (.eml, or Outlook .msg with olefile): its outline, or a bounded line range.

The message is read as lines: From, To, Cc, Date and Subject, a blank line, the
body (text/plain, else the HTML body as text), then the list of attachments.
`--attachments` also reads the attachments that are documents the reader
supports (Word, PDF, Excel, another e-mail ...), within a size and count limit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import add_output_argument, emit, require_path
from mail_text import attachment_documents, attachment_summary, blocks_text, message_lines, read_message

SUFFIXES = {".eml", ".msg"}


def outline(path: Path) -> dict:
    message = read_message(path)
    lines = message_lines(message)
    result = {
        "document": str(path), "type": "email", "format": message["format"],
        "headers": message["headers"],
        "body_type": message["body_type"], "charset": message["charset"],
        "line_count": len(lines),
        # The body starts after the header lines and the blank line under them.
        "body_start_line": lines.index("") + 2,
        "attachment_count": len(message["attachments"]),
        "attachments": [attachment_summary(item) for item in message["attachments"]],
    }
    if message.get("note"):
        result["note"] = message["note"]
    return result


def read(path: Path, start: int | None, end: int | None, max_chars: int, attachments: bool = False) -> dict:
    message = read_message(path)
    lines = message_lines(message)
    first = max(1, start or 1)
    last = min(len(lines), end or len(lines))
    text = "\n".join(lines[first - 1:last])
    result = {
        "document": str(path), "type": "email", "format": message["format"],
        "headers": message["headers"],
        "source": {"start_line": first, "end_line": last},
        "content": text[:max_chars], "truncated": len(text) > max_chars,
        "attachments": [attachment_summary(item) for item in message["attachments"]],
    }
    if message.get("note"):
        result["note"] = message["note"]
    if attachments:
        for summary, entry in zip(result["attachments"], attachment_documents(message, 500)):
            if "blocks" in entry:
                body = blocks_text(entry["blocks"])
                summary.update(read_as=entry["type"], content=body[:max_chars], truncated=len(body) > max_chars)
            else:
                summary["not_read"] = entry["not_read"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document")
    parser.add_argument("--outline-only", action="store_true")
    parser.add_argument("--start-line", type=int)
    parser.add_argument("--end-line", type=int)
    parser.add_argument("--max-chars", type=int, default=12000, help="Limit for the message, and for each attachment read")
    parser.add_argument(
        "--attachments", action="store_true",
        help="Also read the attachments that are supported documents (off by default)",
    )
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        path = require_path(args.document, SUFFIXES)
        if args.max_chars < 1:
            raise ValueError("max-chars must be positive")
        if args.outline_only:
            emit(outline(path), args.output)
        else:
            emit(read(path, args.start_line, args.end_line, args.max_chars, args.attachments), args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
