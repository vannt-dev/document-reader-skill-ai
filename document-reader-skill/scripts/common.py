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
}


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
