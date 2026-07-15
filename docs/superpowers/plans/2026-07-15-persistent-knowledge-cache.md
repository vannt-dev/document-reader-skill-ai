# Persistent Knowledge Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse each requirement document once into a durable normalized JSON cache plus a small always-loaded index, so later coding-agent contexts retrieve requirement detail by querying the cache instead of re-parsing Excel/Markdown.

**Architecture:** Two new deterministic scripts extend the existing `document-reader-skill/scripts/` toolset. `build_cache.py` reads the existing `manifest.json`, extracts full content per document into `.document-reader/cache/<doc-id>.json` (split into self-traceable blocks), and writes a compact `.document-reader/index.json`. `query_cache.py` filters those pre-parsed JSON blocks — never importing `openpyxl` — and flags stale blocks by comparing cached hashes against the manifest. A small pure-Python helper module holds the id/slug/chunking logic so it can be unit-tested without `openpyxl`.

**Tech Stack:** Python 3.10+, `openpyxl` (build only), standard library, `pytest`.

## Global Constraints

- Python floor: **3.10+** (existing scripts use `str | None`, `match :=`).
- Excel support limited to `.xlsx`, `.xlsm`; Markdown to `.md`, `.markdown`. Reject legacy `.xls`.
- Only `build_cache.py` may import `openpyxl`. `query_cache.py` and `cache_common.py` MUST NOT import it.
- All scripts import shared helpers via `from common import ...` (scripts dir is on the path).
- Every script's `main()` returns `int`, prints `error: <msg>` to stderr and returns `2` on failure — matching existing scripts.
- Excel block window default: **500 rows per block**.
- JSON emitted via `common.emit` (UTF-8, `ensure_ascii=False`, indent 2).
- Cache/index/config live under `.document-reader/` (the cache dir); default cache dir is `.document-reader`.
- Never modify files outside the authorized project boundary.

---

## File Structure

- Create `document-reader-skill/scripts/cache_common.py` — pure helpers: `doc_id_for`, `column_letter`, `excel_block_ranges`, `slugify`, `markdown_headings`, `markdown_sections`. No `openpyxl`.
- Create `document-reader-skill/scripts/build_cache.py` — extract full content into `cache/*.json` + `index.json`; incremental by hash.
- Create `document-reader-skill/scripts/query_cache.py` — query cache blocks; stale detection; no `openpyxl`.
- Create `document-reader-skill/scripts/cache_config.py` — `config.json` + `.gitignore` management for share scope.
- Create `document-reader-skill/schemas/document-cache.schema.json` — schema for `index.json`.
- Create `document-reader-skill/pyproject.toml` — pytest config (`pythonpath = ["scripts"]`, `testpaths = ["tests"]`).
- Create `document-reader-skill/tests/conftest.py` — fixtures (`sample_md`, `sample_xlsx`).
- Create `document-reader-skill/tests/test_cache_common.py`, `test_build_cache.py`, `test_query_cache.py`, `test_cache_config.py`, `test_index_schema.py`.
- Modify `document-reader-skill/SKILL.md` — workflow + Commands.
- Modify `document-reader-skill/README.md` — cache build/query sections.

All commands below run from `document-reader-skill/` (the skill root) unless stated.

---

### Task 1: Pure helpers (`cache_common.py`)

**Files:**
- Create: `document-reader-skill/scripts/cache_common.py`
- Create: `document-reader-skill/pyproject.toml`
- Test: `document-reader-skill/tests/test_cache_common.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `doc_id_for(relative_path: str) -> str`
  - `column_letter(index: int) -> str` (1 → "A", 27 → "AA")
  - `excel_block_ranges(max_row: int, window: int) -> list[tuple[int, int]]`
  - `slugify(title: str) -> str`
  - `markdown_headings(lines: list[str]) -> list[dict]` (keys: `level`, `title`, `line`)
  - `markdown_sections(lines: list[str]) -> list[dict]` (keys: `title` (str|None), `level` (int), `start` (int), `end` (int)); sections partition the file with no overlap — each section ends at the line before the next heading of any level.

- [ ] **Step 1: Create pytest config**

Create `document-reader-skill/pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["scripts"]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing tests**

Create `document-reader-skill/tests/test_cache_common.py`:

```python
import cache_common as cc


def test_doc_id_for_slugifies_relative_path():
    assert cc.doc_id_for("api.xlsx") == "api-xlsx"
    assert cc.doc_id_for("sub/Business Rules.md") == "sub-business-rules-md"
    assert cc.doc_id_for("") == "doc"


def test_column_letter():
    assert cc.column_letter(1) == "A"
    assert cc.column_letter(26) == "Z"
    assert cc.column_letter(27) == "AA"


def test_excel_block_ranges_chunks_by_window():
    assert cc.excel_block_ranges(3, 500) == [(1, 3)]
    assert cc.excel_block_ranges(1200, 500) == [(1, 500), (501, 1000), (1001, 1200)]
    assert cc.excel_block_ranges(0, 500) == []


def test_slugify():
    assert cc.slugify("Authentication & Tokens") == "authentication-tokens"
    assert cc.slugify("!!!") == "section"


def test_markdown_sections_partition_without_overlap():
    lines = [
        "# Overview",      # 1
        "Intro.",          # 2
        "# Auth",          # 3
        "Log in.",         # 4
        "## Tokens",       # 5
        "Use JWT.",        # 6
    ]
    sections = cc.markdown_sections(lines)
    assert [(s["title"], s["start"], s["end"]) for s in sections] == [
        ("Overview", 1, 2),
        ("Auth", 3, 4),
        ("Tokens", 5, 6),
    ]


def test_markdown_sections_captures_preamble():
    lines = ["Preamble line.", "# First", "Body."]
    sections = cc.markdown_sections(lines)
    assert sections[0]["title"] is None
    assert (sections[0]["start"], sections[0]["end"]) == (1, 1)


def test_markdown_headings_ignore_fenced_code():
    lines = ["# Real", "```", "# Fake in fence", "```"]
    titles = [h["title"] for h in cc.markdown_headings(lines)]
    assert titles == ["Real"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_cache_common.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cache_common'`.

- [ ] **Step 4: Write the implementation**

Create `document-reader-skill/scripts/cache_common.py`:

```python
"""Pure helpers for building and querying the document cache. No openpyxl."""

from __future__ import annotations

import re

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def doc_id_for(relative_path: str) -> str:
    normalized = relative_path.strip().replace("\\", "/").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug or "doc"


def column_letter(index: int) -> str:
    if index < 1:
        raise ValueError("column index must be >= 1")
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def excel_block_ranges(max_row: int, window: int) -> list[tuple[int, int]]:
    if window < 1:
        raise ValueError("window must be >= 1")
    if max_row < 1:
        return []
    ranges = []
    start = 1
    while start <= max_row:
        end = min(start + window - 1, max_row)
        ranges.append((start, end))
        start = end + 1
    return ranges


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "section"


def markdown_headings(lines: list[str]) -> list[dict]:
    result = []
    fenced = False
    for number, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fenced = not fenced
        if not fenced and (match := HEADING.match(line)):
            result.append({
                "level": len(match.group(1)),
                "title": match.group(2).rstrip("# "),
                "line": number,
            })
    return result


def markdown_sections(lines: list[str]) -> list[dict]:
    headings = markdown_headings(lines)
    sections = []
    first = headings[0]["line"] if headings else len(lines) + 1
    if first > 1 and any(line.strip() for line in lines[: first - 1]):
        sections.append({"title": None, "level": 0, "start": 1, "end": first - 1})
    for index, heading in enumerate(headings):
        start = heading["line"]
        end = headings[index + 1]["line"] - 1 if index + 1 < len(headings) else len(lines)
        sections.append({
            "title": heading["title"],
            "level": heading["level"],
            "start": start,
            "end": end,
        })
    return sections
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_cache_common.py -v`
Expected: PASS (7 passed).

- [ ] **Step 6: Commit**

```bash
git add document-reader-skill/scripts/cache_common.py document-reader-skill/pyproject.toml document-reader-skill/tests/test_cache_common.py
git commit -m "feat: add cache_common pure helpers for document cache"
```

---

### Task 2: Build the cache (`build_cache.py`)

**Files:**
- Create: `document-reader-skill/scripts/build_cache.py`
- Create: `document-reader-skill/tests/conftest.py`
- Test: `document-reader-skill/tests/test_build_cache.py`

**Interfaces:**
- Consumes: `cache_common.doc_id_for`, `column_letter`, `excel_block_ranges`, `slugify`, `markdown_sections`; `common.json_value`, `common.emit`; `index_documents.digest`.
- Produces:
  - `extract_excel(path: Path, window: int) -> list[dict]` — blocks with keys `block_id`, `ref` (`{sheet, range}`), `label`, `content` (`{headers, rows}`); each row is `{row, cells}`.
  - `extract_markdown(path: Path) -> list[dict]` — blocks with `ref` (`{heading, level, lines:[start,end]}`), `content` (`{text}`).
  - `build(manifest_path: Path, cache_dir: Path, window: int, force: bool = False) -> dict` — writes `cache/<doc-id>.json` and `index.json`, returns the index dict. Cache file shape: `{doc_id, path, sha256, type, blocks:[...]}` or, on parse failure, `{doc_id, path, sha256, type, error, blocks:[]}`. Index doc entry: `{doc_id, path, sha256, type, blocks:[{block_id,label}]}` plus `error` when present. Unchanged docs (existing cache `sha256` equals manifest `sha256`) are NOT rewritten.
  - Index dict shape: `{"schema_version": "1.0", "documents": [...]}`.

- [ ] **Step 1: Create shared fixtures**

Create `document-reader-skill/tests/conftest.py`:

```python
import pytest


@pytest.fixture
def sample_md(tmp_path):
    path = tmp_path / "business.md"
    path.write_text(
        "# Overview\nIntro text.\n\n# Authentication\nUsers must log in.\n\n"
        "## Tokens\nUse JWT.\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def sample_xlsx(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "api.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "API"
    sheet.append(["ID", "Requirement", "Status"])
    sheet.append(["REQ-1", "Login endpoint", "pending"])
    sheet.append(["REQ-2", "Logout endpoint", "pending"])
    workbook.save(path)
    return path


@pytest.fixture
def manifest_for(tmp_path):
    """Build a manifest.json referencing given files, return its path."""
    import json
    from index_documents import digest

    def _make(paths, cache_dir):
        documents = []
        for path in paths:
            documents.append({
                "path": path.name,
                "type": "markdown" if path.suffix.lower() in {".md", ".markdown"} else "excel",
                "sha256": digest(path),
            })
        manifest = {
            "schema_version": "1.0",
            "requirements_root": str(tmp_path),
            "documents": documents,
        }
        cache_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = cache_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    return _make
```

- [ ] **Step 2: Write the failing tests**

Create `document-reader-skill/tests/test_build_cache.py`:

```python
import json

import build_cache


def test_build_extracts_markdown_sections(tmp_path, sample_md, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    manifest_path = manifest_for([sample_md], cache_dir)

    index = build_cache.build(manifest_path, cache_dir, window=500)

    doc = index["documents"][0]
    assert doc["doc_id"] == "business-md"
    assert doc["type"] == "markdown"
    labels = [block["label"] for block in doc["blocks"]]
    assert labels == ["Overview", "Authentication", "Tokens"]

    cache_file = cache_dir / "cache" / "business-md.json"
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    auth = next(b for b in cached["blocks"] if b["label"] == "Authentication")
    assert "Users must log in." in auth["content"]["text"]
    assert auth["ref"]["lines"] == [3, 4]


def test_build_extracts_excel_blocks(tmp_path, sample_xlsx, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    manifest_path = manifest_for([sample_xlsx], cache_dir)

    index = build_cache.build(manifest_path, cache_dir, window=500)

    doc = index["documents"][0]
    assert doc["type"] == "excel"
    cache_file = cache_dir / "cache" / "api-xlsx.json"
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    block = cached["blocks"][0]
    assert block["block_id"] == "API!A1:C3"
    assert block["content"]["headers"] == ["ID", "Requirement", "Status"]
    assert block["content"]["rows"][1]["cells"] == ["REQ-1", "Login endpoint", "pending"]


def test_build_is_incremental(tmp_path, sample_md, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    manifest_path = manifest_for([sample_md], cache_dir)
    build_cache.build(manifest_path, cache_dir, window=500)

    cache_file = cache_dir / "cache" / "business-md.json"
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    cached["sentinel"] = True
    cache_file.write_text(json.dumps(cached), encoding="utf-8")

    build_cache.build(manifest_path, cache_dir, window=500)

    reloaded = json.loads(cache_file.read_text(encoding="utf-8"))
    assert reloaded.get("sentinel") is True  # unchanged doc was not rewritten


def test_build_records_parse_error(tmp_path, manifest_for):
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a real workbook")
    cache_dir = tmp_path / ".document-reader"
    manifest_path = manifest_for([broken], cache_dir)

    index = build_cache.build(manifest_path, cache_dir, window=500)

    doc = index["documents"][0]
    assert "error" in doc
    assert doc["blocks"] == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_build_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'build_cache'`.

- [ ] **Step 4: Write the implementation**

Create `document-reader-skill/scripts/build_cache.py`:

```python
#!/usr/bin/env python3
"""Extract full document content into a durable per-document JSON cache."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cache_common import column_letter, doc_id_for, excel_block_ranges, markdown_sections, slugify
from common import add_output_argument, emit, json_value


def extract_markdown(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    blocks = []
    for section in markdown_sections(lines):
        title = section["title"] or "(preamble)"
        text = "\n".join(lines[section["start"] - 1:section["end"]])
        blocks.append({
            "block_id": f"{slugify(title)}@L{section['start']}-{section['end']}",
            "ref": {
                "heading": section["title"],
                "level": section["level"],
                "lines": [section["start"], section["end"]],
            },
            "label": title,
            "content": {"text": text},
        })
    return blocks


def extract_excel(path: Path, window: int) -> list[dict]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    blocks = []
    try:
        for sheet in workbook.worksheets:
            max_row = sheet.max_row or 0
            max_col = sheet.max_column or 0
            if max_row < 1 or max_col < 1:
                continue
            header_cells = next(
                sheet.iter_rows(min_row=1, max_row=1, max_col=max_col, values_only=True), ()
            )
            headers = [json_value(value) for value in header_cells]
            last_col = column_letter(max_col)
            ranges = excel_block_ranges(max_row, window)
            for start, end in ranges:
                rows = []
                for cells in sheet.iter_rows(min_row=start, max_row=end, max_col=max_col):
                    rows.append({
                        "row": cells[0].row,
                        "cells": [json_value(cell.value) for cell in cells],
                    })
                cell_range = f"A{start}:{last_col}{end}"
                label = sheet.title if len(ranges) == 1 else f"{sheet.title} rows {start}-{end}"
                blocks.append({
                    "block_id": f"{sheet.title}!{cell_range}",
                    "ref": {"sheet": sheet.title, "range": cell_range},
                    "label": label,
                    "content": {"headers": headers, "rows": rows},
                })
    finally:
        workbook.close()
    return blocks


def build(manifest_path: Path, cache_dir: Path, window: int, force: bool = False) -> dict:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    root = Path(manifest["requirements_root"])
    cache_subdir = cache_dir / "cache"
    cache_subdir.mkdir(parents=True, exist_ok=True)
    documents = []
    for entry in manifest.get("documents", []):
        rel = entry["path"]
        doc_id = doc_id_for(rel)
        sha256 = entry.get("sha256", "")
        doc_type = entry.get("type", "excel")
        cache_file = cache_subdir / f"{doc_id}.json"

        if not force and cache_file.is_file():
            existing = json.loads(cache_file.read_text(encoding="utf-8"))
            if existing.get("sha256") == sha256:
                documents.append(_index_entry(existing))
                continue

        cache_payload = {"doc_id": doc_id, "path": rel, "sha256": sha256, "type": doc_type}
        try:
            source = root / rel
            if doc_type == "markdown":
                cache_payload["blocks"] = extract_markdown(source)
            else:
                cache_payload["blocks"] = extract_excel(source, window)
        except Exception as exc:  # noqa: BLE001 - record, do not abort the whole build
            cache_payload["blocks"] = []
            cache_payload["error"] = str(exc)

        cache_file.write_text(
            json.dumps(cache_payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        documents.append(_index_entry(cache_payload))

    index = {"schema_version": "1.0", "documents": documents}
    (cache_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return index


def _index_entry(cache_payload: dict) -> dict:
    entry = {
        "doc_id": cache_payload["doc_id"],
        "path": cache_payload["path"],
        "sha256": cache_payload.get("sha256", ""),
        "type": cache_payload.get("type", "unknown"),
        "blocks": [
            {"block_id": block["block_id"], "label": block["label"]}
            for block in cache_payload.get("blocks", [])
        ],
    }
    if "error" in cache_payload:
        entry["error"] = cache_payload["error"]
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=".document-reader/manifest.json")
    parser.add_argument("--cache-dir", default=".document-reader")
    parser.add_argument("--max-block-rows", type=int, default=500)
    parser.add_argument("--force", action="store_true")
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        if args.max_block_rows < 1:
            raise ValueError("max-block-rows must be positive")
        manifest_path = Path(args.manifest)
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}; run index_documents.py first")
        index = build(manifest_path, Path(args.cache_dir), args.max_block_rows, args.force)
        emit({
            "cache_dir": args.cache_dir,
            "documents": len(index["documents"]),
            "errors": [d["doc_id"] for d in index["documents"] if "error" in d],
        }, args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_build_cache.py -v`
Expected: PASS (4 passed). If `openpyxl` is missing, run `python -m pip install openpyxl` first.

- [ ] **Step 6: Commit**

```bash
git add document-reader-skill/scripts/build_cache.py document-reader-skill/tests/conftest.py document-reader-skill/tests/test_build_cache.py
git commit -m "feat: add build_cache to extract full document content into cache"
```

---

### Task 3: Query the cache (`query_cache.py`)

**Files:**
- Create: `document-reader-skill/scripts/query_cache.py`
- Test: `document-reader-skill/tests/test_query_cache.py`

**Interfaces:**
- Consumes: `index.json` and `cache/<doc-id>.json` written by Task 2; optional `manifest.json` for stale detection. Does NOT import `cache_common` or `openpyxl`.
- Produces:
  - `query(cache_dir: Path, keyword: str | None = None, doc: str | None = None, block_id: str | None = None, label: str | None = None, max_results: int = 50) -> dict`.
  - Result shape: `{"schema_version": "1.0", "query": {...}, "results": [...], "truncated": bool, "warnings": [...]}`. Each result: `{doc_id, path, block_id, ref, label, stale}` plus `content` when not stale. Stale results omit `content` and set `stale: true`.

- [ ] **Step 1: Write the failing tests**

Create `document-reader-skill/tests/test_query_cache.py`:

```python
import json
from pathlib import Path

import query_cache


def _seed(cache_dir: Path, manifest_sha="hash-1"):
    (cache_dir / "cache").mkdir(parents=True, exist_ok=True)
    cache_payload = {
        "doc_id": "api-md", "path": "api.md", "sha256": "hash-1", "type": "markdown",
        "blocks": [
            {"block_id": "auth@L1-2", "ref": {"heading": "Auth", "lines": [1, 2]},
             "label": "Auth", "content": {"text": "Users must log in with a password."}},
            {"block_id": "logout@L3-4", "ref": {"heading": "Logout", "lines": [3, 4]},
             "label": "Logout", "content": {"text": "Users can sign out."}},
        ],
    }
    (cache_dir / "cache" / "api-md.json").write_text(json.dumps(cache_payload), encoding="utf-8")
    index = {"schema_version": "1.0", "documents": [{
        "doc_id": "api-md", "path": "api.md", "sha256": "hash-1", "type": "markdown",
        "blocks": [{"block_id": "auth@L1-2", "label": "Auth"},
                   {"block_id": "logout@L3-4", "label": "Logout"}],
    }]}
    (cache_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    manifest = {"requirements_root": "/x", "documents": [
        {"path": "api.md", "type": "markdown", "sha256": manifest_sha}]}
    (cache_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_query_keyword_returns_matching_block(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    _seed(cache_dir)
    result = query_cache.query(cache_dir, keyword="password")
    assert [r["block_id"] for r in result["results"]] == ["auth@L1-2"]
    assert result["results"][0]["content"]["text"].startswith("Users must log in")


def test_query_by_block_id(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    _seed(cache_dir)
    result = query_cache.query(cache_dir, block_id="logout@L3-4")
    assert [r["label"] for r in result["results"]] == ["Logout"]


def test_query_flags_stale_and_withholds_content(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    _seed(cache_dir, manifest_sha="hash-2")  # manifest hash differs from cache
    result = query_cache.query(cache_dir, keyword="password")
    assert result["results"][0]["stale"] is True
    assert "content" not in result["results"][0]
    assert any("stale" in w for w in result["warnings"])


def test_query_reports_missing_cache(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    result = query_cache.query(cache_dir, keyword="password")
    assert result["results"] == []
    assert any("index.json" in w for w in result["warnings"])


def test_query_cache_never_imports_openpyxl():
    source = Path(query_cache.__file__).read_text(encoding="utf-8")
    assert "openpyxl" not in source
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_query_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'query_cache'`.

- [ ] **Step 3: Write the implementation**

Create `document-reader-skill/scripts/query_cache.py`:

```python
#!/usr/bin/env python3
"""Query the pre-parsed document cache without re-reading source files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import add_output_argument, emit


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _manifest_hashes(cache_dir: Path) -> dict[str, str]:
    manifest = _load_json(cache_dir / "manifest.json")
    if not manifest:
        return {}
    return {doc["path"]: doc.get("sha256", "") for doc in manifest.get("documents", [])}


def query(cache_dir, keyword=None, doc=None, block_id=None, label=None, max_results=50) -> dict:
    cache_dir = Path(cache_dir)
    warnings: list[str] = []
    index = _load_json(cache_dir / "index.json")
    if not index:
        warnings.append("No index.json found; run build_cache.py first.")
        return _envelope(keyword, doc, block_id, label, [], False, warnings)

    manifest_hashes = _manifest_hashes(cache_dir)
    needle = keyword.casefold() if keyword else None
    label_needle = label.casefold() if label else None
    results: list[dict] = []
    truncated = False

    for document in index.get("documents", []):
        if doc and document["doc_id"] != doc:
            continue
        current = manifest_hashes.get(document["path"])
        stale = current is not None and current != document.get("sha256")
        cache_payload = _load_json(cache_dir / "cache" / f"{document['doc_id']}.json")
        blocks = cache_payload.get("blocks", []) if cache_payload else []
        for block in blocks:
            if block_id and block["block_id"] != block_id:
                continue
            if label_needle and label_needle not in block["label"].casefold():
                continue
            if needle:
                haystack = (block["label"] + json.dumps(block["content"], ensure_ascii=False)).casefold()
                if needle not in haystack:
                    continue
            result = {
                "doc_id": document["doc_id"],
                "path": document["path"],
                "block_id": block["block_id"],
                "ref": block["ref"],
                "label": block["label"],
                "stale": stale,
            }
            if stale:
                warnings.append(f"{document['doc_id']} is stale; rebuild with build_cache.py.")
            else:
                result["content"] = block["content"]
            results.append(result)
            if len(results) >= max_results:
                truncated = True
                break
        if truncated:
            break

    return _envelope(keyword, doc, block_id, label, results, truncated, warnings)


def _envelope(keyword, doc, block_id, label, results, truncated, warnings) -> dict:
    return {
        "schema_version": "1.0",
        "query": {"keyword": keyword, "doc": doc, "block_id": block_id, "label": label},
        "results": results,
        "truncated": truncated,
        "warnings": sorted(set(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("keyword", nargs="?", help="Case-insensitive keyword over label and content")
    parser.add_argument("--cache-dir", default=".document-reader")
    parser.add_argument("--doc", help="Restrict to a doc_id")
    parser.add_argument("--block-id", help="Return exactly this block")
    parser.add_argument("--label", help="Case-insensitive label substring")
    parser.add_argument("--max-results", type=int, default=50)
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        if args.max_results < 1:
            raise ValueError("max-results must be positive")
        result = query(
            args.cache_dir, args.keyword, args.doc, args.block_id, args.label, args.max_results
        )
        emit(result, args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_query_cache.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add document-reader-skill/scripts/query_cache.py document-reader-skill/tests/test_query_cache.py
git commit -m "feat: add query_cache for cached blocks with stale detection"
```

---

### Task 4: Share scope config (`cache_config.py` + `--share`)

**Files:**
- Create: `document-reader-skill/scripts/cache_config.py`
- Modify: `document-reader-skill/scripts/build_cache.py` (add `--share`, wire config)
- Test: `document-reader-skill/tests/test_cache_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `write_config(cache_dir: Path, share: str) -> None` — writes `config.json` = `{"share": share}`; `share` must be `"local"` or `"commit"`.
  - `apply_gitignore(project_dir: Path, share: str) -> None` — for `local`, ensures a marked block ignoring `.document-reader/cache/`, `.document-reader/index.json`, `.document-reader/manifest.json`; for `commit`, removes that block. Idempotent.

- [ ] **Step 1: Write the failing tests**

Create `document-reader-skill/tests/test_cache_config.py`:

```python
import json

import cache_config


def test_write_config(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    cache_config.write_config(cache_dir, "commit")
    data = json.loads((cache_dir / "config.json").read_text(encoding="utf-8"))
    assert data == {"share": "commit"}


def test_write_config_rejects_unknown_scope(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        cache_config.write_config(tmp_path, "public")


def test_apply_gitignore_local_is_idempotent(tmp_path):
    cache_config.apply_gitignore(tmp_path, "local")
    cache_config.apply_gitignore(tmp_path, "local")
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert text.count(".document-reader/cache/") == 1
    assert ".document-reader/index.json" in text


def test_apply_gitignore_commit_removes_block(tmp_path):
    cache_config.apply_gitignore(tmp_path, "local")
    cache_config.apply_gitignore(tmp_path, "commit")
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8") if (tmp_path / ".gitignore").exists() else ""
    assert ".document-reader/cache/" not in text


def test_apply_gitignore_preserves_existing_entries(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    cache_config.apply_gitignore(tmp_path, "local")
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "node_modules/" in text
    assert ".document-reader/cache/" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cache_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cache_config'`.

- [ ] **Step 3: Write the implementation**

Create `document-reader-skill/scripts/cache_config.py`:

```python
"""Share-scope config and .gitignore management for the document cache."""

from __future__ import annotations

import json
from pathlib import Path

SHARE_LOCAL = "local"
SHARE_COMMIT = "commit"
VALID_SHARE = {SHARE_LOCAL, SHARE_COMMIT}

GITIGNORE_MARK = "# document-reader cache (share=local)"
IGNORE_LINES = [
    ".document-reader/cache/",
    ".document-reader/index.json",
    ".document-reader/manifest.json",
]


def write_config(cache_dir: Path, share: str) -> None:
    if share not in VALID_SHARE:
        raise ValueError(f"Unknown share scope {share!r}; use 'local' or 'commit'")
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "config.json").write_text(
        json.dumps({"share": share}, indent=2) + "\n", encoding="utf-8"
    )


def apply_gitignore(project_dir: Path, share: str) -> None:
    if share not in VALID_SHARE:
        raise ValueError(f"Unknown share scope {share!r}; use 'local' or 'commit'")
    gitignore = Path(project_dir) / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.is_file() else []
    has_mark = GITIGNORE_MARK in lines

    if share == SHARE_LOCAL:
        if has_mark:
            return
        block = [GITIGNORE_MARK, *IGNORE_LINES]
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(block)
    else:  # commit: strip our managed block
        managed = {GITIGNORE_MARK, *IGNORE_LINES}
        lines = [line for line in lines if line not in managed]

    if lines:
        gitignore.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif gitignore.is_file():
        gitignore.write_text("", encoding="utf-8")
```

- [ ] **Step 4: Wire `--share` into build_cache**

In `document-reader-skill/scripts/build_cache.py`, add the import near the top (after the existing `from common import ...` line):

```python
import cache_config
```

In `build_cache.py` `main()`, add the argument after the `--force` line:

```python
    parser.add_argument("--share", choices=["local", "commit"], help="Set cache share scope and adjust .gitignore")
```

In `build_cache.py` `main()`, immediately after `index = build(...)` and before `emit(`, insert:

```python
        if args.share:
            cache_dir = Path(args.cache_dir)
            cache_config.write_config(cache_dir, args.share)
            cache_config.apply_gitignore(cache_dir.parent, args.share)
            if args.share == "commit":
                print("warning: share=commit will version cache content; verify documents contain no secrets.", file=sys.stderr)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_cache_config.py tests/test_build_cache.py -v`
Expected: PASS (all config tests + the 4 build tests still green).

- [ ] **Step 6: Commit**

```bash
git add document-reader-skill/scripts/cache_config.py document-reader-skill/scripts/build_cache.py document-reader-skill/tests/test_cache_config.py
git commit -m "feat: add share-scope config and gitignore management"
```

---

### Task 5: Schema and documentation

**Files:**
- Create: `document-reader-skill/schemas/document-cache.schema.json`
- Test: `document-reader-skill/tests/test_index_schema.py`
- Modify: `document-reader-skill/SKILL.md`
- Modify: `document-reader-skill/README.md`

**Interfaces:**
- Consumes: `index.json` shape from Task 2.
- Produces: a JSON Schema and updated docs. No new runtime code.

- [ ] **Step 1: Write the failing structural test**

Create `document-reader-skill/tests/test_index_schema.py` (validates the built index against the schema's required keys using stdlib only — no `jsonschema` dependency):

```python
import json
from pathlib import Path

import build_cache

SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "document-cache.schema.json"


def test_schema_file_is_valid_json():
    data = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert data["title"] == "Document Reader Cache Index"


def test_built_index_matches_schema_required_keys(tmp_path, sample_md, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    manifest_path = manifest_for([sample_md], cache_dir)
    index = build_cache.build(manifest_path, cache_dir, window=500)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    top_required = schema["required"]
    assert all(key in index for key in top_required)
    doc_required = schema["properties"]["documents"]["items"]["required"]
    for document in index["documents"]:
        assert all(key in document for key in doc_required)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_schema.py -v`
Expected: FAIL — schema file does not exist (`FileNotFoundError`).

- [ ] **Step 3: Create the schema**

Create `document-reader-skill/schemas/document-cache.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.local/document-reader/document-cache.schema.json",
  "title": "Document Reader Cache Index",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "documents"],
  "properties": {
    "schema_version": { "const": "1.0" },
    "documents": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["doc_id", "path", "sha256", "type", "blocks"],
        "properties": {
          "doc_id": { "type": "string" },
          "path": { "type": "string" },
          "sha256": { "type": "string" },
          "type": { "enum": ["excel", "markdown", "unknown"] },
          "error": { "type": "string" },
          "blocks": {
            "type": "array",
            "items": {
              "type": "object",
              "additionalProperties": false,
              "required": ["block_id", "label"],
              "properties": {
                "block_id": { "type": "string" },
                "label": { "type": "string" }
              }
            }
          }
        }
      }
    }
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_index_schema.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Update SKILL.md**

In `document-reader-skill/SKILL.md`, in the **"Bootstrap from a folder path"** numbered list, replace step 3 with these two steps (renumber the rest):

```markdown
3. Run `scripts/index_documents.py REQUIREMENTS_FOLDER --output .document-reader/manifest.json` from the project.
4. Run `scripts/build_cache.py --manifest .document-reader/manifest.json` to extract full content into `.document-reader/cache/` and `.document-reader/index.json`.
```

In `SKILL.md`, in the **"Persist knowledge across contexts"** bullet list, add:

```markdown
- Store full normalized content once in `.document-reader/cache/<doc-id>.json` and a small catalog in `.document-reader/index.json` via `build_cache.py`.
- At the start of a later context, load `index.json` (not the whole cache); fetch detail with `query_cache.py` instead of re-parsing source documents.
- Rebuild only documents whose manifest hash changed; `query_cache.py` flags stale blocks and withholds their content until rebuilt.
```

In `SKILL.md`, in the **Commands** fenced block, add:

```bash
python scripts/build_cache.py --manifest .document-reader/manifest.json --max-block-rows 500
python scripts/query_cache.py "authentication" --doc api-xlsx --max-results 25
```

- [ ] **Step 6: Update README.md**

In `document-reader-skill/README.md`, under the persistent-context section, add a subsection describing `build_cache.py` (creates `cache/` + `index.json`, incremental by hash, `--share local|commit`) and `query_cache.py` (queries cached blocks by keyword/`--doc`/`--block-id`/`--label`, flags stale, never re-parses source). Include:

```bash
python scripts/build_cache.py --manifest .document-reader/manifest.json --share local
python scripts/query_cache.py "authentication" --output context.json
```

- [ ] **Step 7: Run the full test suite**

Run: `python -m pytest -v`
Expected: PASS (all tests from Tasks 1–5 green).

- [ ] **Step 8: Commit**

```bash
git add document-reader-skill/schemas/document-cache.schema.json document-reader-skill/tests/test_index_schema.py document-reader-skill/SKILL.md document-reader-skill/README.md
git commit -m "docs: add cache schema and document build_cache/query_cache workflow"
```

---

## Self-Review Notes

- **Spec coverage:** two-layer storage (Tasks 2, existing knowledge.md) ✓; purpose-neutral content (Task 2 stores raw blocks) ✓; small index + on-demand query (Tasks 2–3) ✓; user-configurable sharing (Task 4) ✓; stale handling (Task 3) ✓; block granularity — Excel per-sheet/windowed, Markdown per-heading (Task 1–2) ✓; error handling per document (Task 2) ✓; query never re-parses (Task 3 test) ✓; schema + SKILL.md integration (Task 5) ✓; pytest (Task 1 config) ✓.
- **Type consistency:** block shape `{block_id, ref, label, content}` is identical in `extract_excel`, `extract_markdown`, and consumed unchanged by `query_cache`; index entry `{doc_id, path, sha256, type, blocks:[{block_id,label}]}` matches the schema's required keys and the `test_index_schema` assertions.
- **Out of scope (per spec):** SQLite/embeddings, automatic secret redaction, adapter changes.
```