"""Shared helpers for document-reader command-line tools."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DOCUMENT_TYPES = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".xlsx": "excel",
    ".xlsm": "excel",
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "text",
    ".html": "html",
    ".htm": "html",
}

# Byte-order marks, longest first: the UTF-32 LE mark starts with the UTF-16 LE one.
BOMS = [
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
]


def decode_text(data: bytes, declared: str | None = None) -> tuple[str, str]:
    """Return (text, encoding) for the bytes of a text file.

    A byte-order mark wins, then an encoding the file declares itself (an HTML
    meta charset), then UTF-8. UTF-16 without a mark is recognised by its zero
    bytes. Windows-1252 is the last resort; it never fails, so a file always
    reads, at worst with a few wrong characters.
    """
    for mark, encoding in BOMS:
        if data.startswith(mark):
            body = data[len(mark):] if encoding != "utf-8-sig" else data
            return body.decode(encoding, errors="replace"), encoding.replace("-sig", "")
    if declared:
        try:
            return data.decode(declared), declared.lower()
        except (LookupError, UnicodeDecodeError):
            pass
    sample = data[:4096]
    if len(sample) >= 2 and sample.count(0) * 4 >= len(sample):
        # Text in UTF-16 is full of zero bytes; which half they sit in says the byte order.
        encoding = "utf-16-le" if sample[1::2].count(0) > sample[0::2].count(0) else "utf-16-be"
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), "cp1252"


def add_output_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", help="Write JSON to this file instead of stdout")


def emit(payload: Any, output: str | None = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if output:
        destination = Path(output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def require_path(raw: str, suffixes: set[str]) -> Path:
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Document not found: {path}")
    if path.suffix.lower() not in suffixes:
        expected = ", ".join(sorted(suffixes))
        raise ValueError(f"Unsupported document type {path.suffix!r}; expected {expected}")
    return path


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
