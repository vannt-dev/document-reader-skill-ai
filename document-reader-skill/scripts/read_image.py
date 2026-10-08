#!/usr/bin/env python3
"""Read the text in an image (a screenshot, a scanned page, a photo of a document) with OCR."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import ocr
from common import add_output_argument, emit, require_path


def read(path: Path, max_chars: int, ocr_lang: str | None = None) -> dict:
    languages = ocr.resolve_languages(ocr_lang)
    content = ocr.image_text(path, languages)
    return {
        "document": str(path), "type": "image",
        "content": content[:max_chars], "truncated": len(content) > max_chars,
        # Always present: every character of an image's text is recognised,
        # and a reader should treat it as such.
        "ocr": ocr.describe(languages),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document")
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--ocr-lang", help="Languages to read, such as vie+eng (default: Vietnamese and English)")
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        path = require_path(args.document, ocr.IMAGE_SUFFIXES)
        if args.max_chars < 1:
            raise ValueError("max-chars must be positive")
        emit(read(path, args.max_chars, args.ocr_lang), args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
