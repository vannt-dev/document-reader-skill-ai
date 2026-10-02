#!/usr/bin/env python3
"""Normalize reader/search JSON into the document-result schema."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from common import add_output_argument, emit


def source_ref(payload: dict[str, Any]) -> dict[str, Any]:
    ref = {"document": payload.get("document", ""), "type": payload.get("type", "unknown")}
    for key in ("sheet", "source", "query"):
        if key in payload:
            ref[key] = payload[key]
    return ref


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="JSON file produced by another script, or - for stdin")
    parser.add_argument("--query", default="")
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        payload = json.loads(raw)
        blocks = []
        if "matches" in payload:
            blocks = [{"kind": "match", "source": source_ref(payload), "data": item} for item in payload["matches"]]
        elif payload.get("type") == "excel" and "rows" in payload:
            blocks = [{"kind": "table", "source": source_ref(payload), "data": {"headers": payload.get("headers", []), "rows": payload["rows"]}}]
        elif payload.get("type") in {"markdown", "pdf", "docx"} and "content" in payload:
            blocks = [{"kind": "text", "source": source_ref(payload), "data": payload["content"]}]
        elif "sheets" in payload or "outline" in payload:
            blocks = [{"kind": "structure", "source": source_ref(payload), "data": payload.get("sheets", payload.get("outline"))}]
        elif payload.get("type") == "pdf" and "pages" in payload:
            data = {"page_count": payload.get("page_count"), "pages": payload["pages"], "bookmarks": payload.get("bookmarks", [])}
            blocks = [{"kind": "structure", "source": source_ref(payload), "data": data}]
        else:
            raise ValueError("Unrecognized reader output")
        warnings = []
        if payload.get("truncated"):
            warnings.append("Output was truncated by a configured safety limit.")
        if payload.get("pages_without_text"):
            pages = ", ".join(str(page) for page in payload["pages_without_text"])
            warnings.append(f"No text could be extracted from page(s) {pages}; they may be scanned images.")
        emit({
            "schema_version": "1.0", "query": args.query,
            "documents": [{"path": payload.get("document", ""), "type": payload.get("type", "unknown")}],
            "blocks": blocks, "warnings": warnings,
        }, args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

