#!/usr/bin/env python3
"""Inspect a CSV/TSV file or read a bounded, optionally filtered, row range."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import add_output_argument, emit, require_path
from csv_text import csv_rows
from read_excel import parse_filters


def outline(path: Path, preview_rows: int = 5, max_columns: int = 30) -> dict:
    delimiter, rows = csv_rows(path)
    preview, count, columns = [], 0, 0
    for number, cells in rows:
        count = number
        columns = max(columns, len(cells))
        if number <= preview_rows:
            preview.append(cells[:max_columns])
    return {
        "document": str(path), "type": "csv", "delimiter": delimiter,
        "rows": count, "columns": columns,
        "preview": preview, "preview_truncated_columns": columns > max_columns,
    }


def read(
    path: Path,
    start_row: int | None,
    end_row: int | None,
    filters: dict[str, str],
    max_rows: int,
    max_columns: int,
    header_row: int = 1,
) -> dict:
    _, rows = csv_rows(path)
    headers: list[str] = []
    selected, scanned, truncated = [], 0, False
    first = max(start_row or header_row, 1)
    header_index: dict[str, int] = {}
    for number, cells in rows:
        cells = cells[:max_columns]
        if number == header_row:
            headers = cells
            header_index = {value.strip(): index for index, value in enumerate(cells) if value.strip()}
            missing = sorted(set(filters) - set(header_index))
            if missing:
                raise ValueError(f"Filter headers not found: {missing}")
        if number < first:
            continue
        if end_row is not None and number > end_row:
            break
        scanned += 1
        if filters and number != header_row:
            if not all(
                filters[key] in (cells[header_index[key]] if header_index[key] < len(cells) else "").casefold()
                for key in filters
            ):
                continue
        if len(selected) >= max_rows:
            truncated = True
            break
        selected.append({"row": number, "cells": cells})
    if filters and not headers:
        raise ValueError(f"Header row {header_row} not found")
    return {
        "document": str(path), "type": "csv",
        "source": {
            "start_row": first,
            "end_row": selected[-1]["row"] if selected else None,
        },
        "headers": headers, "rows": selected,
        "scanned_rows": scanned, "truncated": truncated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document")
    parser.add_argument("--outline-only", action="store_true")
    parser.add_argument("--preview-rows", type=int, default=5)
    parser.add_argument("--start-row", type=int)
    parser.add_argument("--end-row", type=int)
    parser.add_argument("--header-row", type=int, default=1)
    parser.add_argument("--filter", action="append", default=[], metavar="HEADER=VALUE")
    parser.add_argument("--max-rows", type=int, default=100)
    parser.add_argument("--max-columns", type=int, default=50)
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        path = require_path(args.document, {".csv", ".tsv"})
        if min(args.max_rows, args.max_columns, args.header_row) < 1 or args.preview_rows < 0:
            raise ValueError("row and column limits must be positive")
        if args.outline_only:
            emit(outline(path, args.preview_rows, args.max_columns), args.output)
        else:
            emit(read(
                path, args.start_row, args.end_row, parse_filters(args.filter),
                args.max_rows, args.max_columns, args.header_row,
            ), args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
