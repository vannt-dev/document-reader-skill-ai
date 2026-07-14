#!/usr/bin/env python3
"""Search Excel cells or Markdown lines and return compact cited matches."""

from __future__ import annotations

import argparse
import re
import sys

from common import add_output_argument, emit, json_value, require_path


def matcher(query: str, regex: bool, case_sensitive: bool):
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(query if regex else re.escape(query), flags)
    return pattern.search


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document")
    parser.add_argument("query")
    parser.add_argument("--sheet", action="append", default=[])
    parser.add_argument("--regex", action="store_true")
    parser.add_argument("--case-sensitive", action="store_true")
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--context-lines", type=int, default=1)
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        path = require_path(args.document, {".xlsx", ".xlsm", ".md", ".markdown"})
        if args.max_results < 1 or args.context_lines < 0:
            raise ValueError("max-results must be positive and context-lines non-negative")
        matches, truncated = [], False
        find = matcher(args.query, args.regex, args.case_sensitive)
        if path.suffix.lower() in {".md", ".markdown"}:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
            hit_lines = [number for number, line in enumerate(lines, 1) if find(line)]
            truncated = len(hit_lines) > args.max_results
            for number in hit_lines[:args.max_results]:
                start, end = max(1, number - args.context_lines), min(len(lines), number + args.context_lines)
                matches.append({"line": number, "context_start": start, "context_end": end, "text": "\n".join(lines[start - 1:end])})
            kind = "markdown"
        else:
            from openpyxl import load_workbook

            workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
            names = args.sheet or workbook.sheetnames
            unknown = sorted(set(names) - set(workbook.sheetnames))
            if unknown:
                raise ValueError(f"Unknown sheets: {unknown}")
            for name in names:
                for row in workbook[name].iter_rows():
                    for cell in row:
                        value = json_value(cell.value)
                        if value is not None and find(str(value)):
                            matches.append({"sheet": name, "cell": cell.coordinate, "value": value})
                            if len(matches) >= args.max_results:
                                truncated = True
                                break
                    if truncated:
                        break
                if truncated:
                    break
            workbook.close()
            kind = "excel"
        emit({"document": str(path), "type": kind, "query": args.query, "matches": matches, "truncated": truncated}, args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

