"""Reading delimited text (.csv, .tsv) with the standard library only."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

# A cell this large is a sign the delimiter was guessed wrong, not real data.
csv.field_size_limit(16 * 1024 * 1024)

SNIFF_BYTES = 64 * 1024
CANDIDATE_DELIMITERS = ",;\t|"


def _decode(path: Path) -> str:
    """UTF-8 (with or without a BOM), else Windows-1252, which never fails."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def detect_delimiter(path: Path, sample: str) -> str:
    if path.suffix.lower() == ".tsv":
        return "\t"
    try:
        return csv.Sniffer().sniff(sample[:SNIFF_BYTES], delimiters=CANDIDATE_DELIMITERS).delimiter
    except csv.Error:
        return ","


def csv_rows(path: Path) -> tuple[str, Iterator[tuple[int, list[str]]]]:
    """Return the delimiter and an iterator of (1-based row number, cells).

    Blank lines are skipped, as the csv module does, so row numbers count
    records rather than physical lines; a quoted cell may span several lines.
    """
    # One line-ending convention, so a multi-line cell reads the same whether
    # the file was saved on Windows or not.
    text = _decode(path).replace("\r\n", "\n")
    delimiter = detect_delimiter(path, text)

    def rows() -> Iterator[tuple[int, list[str]]]:
        reader = csv.reader(text.splitlines(keepends=True), delimiter=delimiter)
        number = 0
        for cells in reader:
            if not cells:
                continue
            number += 1
            yield number, cells

    return delimiter, rows()
