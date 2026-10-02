"""Table extraction from PDF pages.

Optional: needs pdfplumber, which is heavier than the rest of the skill. The
plain-text PDF reader works without it.
"""

from __future__ import annotations

import logging
from pathlib import Path

INSTALL_HINT = "PDF table extraction requires pdfplumber: python -m pip install pdfplumber"


def available() -> bool:
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        return False
    return True


def _clean(cell) -> str:
    """One line per cell: a wrapped cell reads as a sentence, not as rows."""
    if cell is None:
        return ""
    return " ".join(str(cell).split())


def extract_tables(path: Path, first: int | None = None, last: int | None = None) -> list[dict]:
    """Tables on pages `first`..`last` (1-based, inclusive; the whole file by default).

    Each table carries its `page`, its 1-based `table` number on that page and
    its `rows` as lists of strings. A table is whatever pdfplumber finds from
    the ruling lines on the page; a table drawn without lines is not detected.
    """
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc
    # pdfminer warns about every font it cannot measure; that is noise on
    # stderr for a reader whose callers look there for real errors.
    logging.getLogger("pdfminer").setLevel(logging.ERROR)

    tables = []
    with pdfplumber.open(str(path)) as pdf:
        count = len(pdf.pages)
        start = max(first or 1, 1)
        end = min(last or count, count)
        for number in range(start, end + 1):
            try:
                found = pdf.pages[number - 1].extract_tables()
            except Exception:  # noqa: BLE001 - one unreadable page must not hide the others
                continue
            position = 0
            for table in found:
                rows = [[_clean(cell) for cell in row] for row in table if row]
                rows = [row for row in rows if any(row)]
                if not rows:
                    continue
                position += 1
                tables.append({"page": number, "table": position, "rows": rows})
    return tables
