import json

import pytest

import build_cache
import pdf_tables
import query_cache
import read_pdf
from conftest import text_at, write_raw_pdf

pytest.importorskip("pypdf")


def ruled_table(rows, left=72, top=700, column_width=170, row_height=20):
    """A table drawn the way a word processor exports one: a grid of lines with text inside."""
    columns = len(rows[0])
    right = left + column_width * columns
    bottom = top - row_height * len(rows)
    parts = ["0.5 w"]
    for index in range(len(rows) + 1):
        y = top - row_height * index
        parts.append(f"{left} {y} m {right} {y} l S")
    for index in range(columns + 1):
        x = left + column_width * index
        parts.append(f"{x} {top} m {x} {bottom} l S")
    for row_index, row in enumerate(rows):
        for column_index, cell in enumerate(row):
            parts.append(text_at(left + column_width * column_index + 4, top - row_height * row_index - 14, cell))
    return " ".join(parts)


RULES = [["ID", "Rule", "Status"], ["R-1", "Lock after 5 attempts", "pending"], ["R-2", "Expire sessions", "done"]]


@pytest.fixture
def table_pdf(tmp_path):
    pytest.importorskip("pdfplumber")
    return write_raw_pdf(tmp_path / "rules.pdf", [
        text_at(72, 740, "Security rules") + " " + ruled_table(RULES),
        text_at(72, 740, "A page with only prose."),
        ruled_table([["Key", "Value"], ["timeout", "30"]]) + " "
        + ruled_table([["Role", "Scope"], ["admin", "all"]], top=500),
    ])


def test_extract_tables_finds_ruled_tables_with_their_page_and_position(table_pdf):
    tables = pdf_tables.extract_tables(table_pdf)

    assert [(table["page"], table["table"]) for table in tables] == [(1, 1), (3, 1), (3, 2)]
    assert tables[0]["rows"] == RULES
    assert tables[1]["rows"] == [["Key", "Value"], ["timeout", "30"]]
    assert tables[2]["rows"] == [["Role", "Scope"], ["admin", "all"]]

    assert [table["page"] for table in pdf_tables.extract_tables(table_pdf, 2, 2)] == []
    assert [table["page"] for table in pdf_tables.extract_tables(table_pdf, 3, 99)] == [3, 3]


def test_read_pdf_tables_reports_shape_and_caps_rows(table_pdf):
    everything = read_pdf.tables(table_pdf, None, 100)
    assert everything["source"] == {"start_page": 1, "end_page": 3}
    assert everything["truncated"] is False
    first = everything["tables"][0]
    assert (first["page"], first["table"], first["rows"], first["columns"]) == (1, 1, 3, 3)
    assert first["cells"] == RULES

    capped = read_pdf.tables(table_pdf, "1", 2)
    assert capped["truncated"] is True
    assert capped["tables"][0]["rows"] == 3
    assert capped["tables"][0]["cells"] == RULES[:2]

    assert read_pdf.tables(table_pdf, "2", 100)["tables"] == []


def test_build_cache_adds_table_blocks_that_a_query_returns_with_headers(tmp_path, table_pdf, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    index = build_cache.build(manifest_for([table_pdf], cache_dir), cache_dir, window=500)

    block_ids = [block["block_id"] for block in index["documents"][0]["blocks"]]
    assert block_ids == ["page-1", "page-2", "page-3", "page-1-table-1", "page-3-table-1", "page-3-table-2"]

    cached = json.loads((cache_dir / "cache" / "rules-pdf.json").read_text(encoding="utf-8"))
    table = next(block for block in cached["blocks"] if block["block_id"] == "page-1-table-1")
    assert table["ref"] == {"page": 1, "table": 1}
    assert table["content"]["headers"] == ["ID", "Rule", "Status"]
    assert table["content"]["rows"] == [
        {"row": 2, "cells": ["R-1", "Lock after 5 attempts", "pending"]},
        {"row": 3, "cells": ["R-2", "Expire sessions", "done"]},
    ]

    result = query_cache.query(cache_dir, label="table", keyword="timeout")
    assert [r["block_id"] for r in result["results"]] == ["page-3-table-1"]


def test_cache_and_reader_without_pdfplumber(tmp_path, table_pdf, manifest_for, monkeypatch):
    monkeypatch.setattr(pdf_tables, "available", lambda: False)
    cache_dir = tmp_path / ".document-reader"
    index = build_cache.build(manifest_for([table_pdf], cache_dir), cache_dir, window=500)

    # The page text is still cached; only the table blocks are missing.
    assert [block["block_id"] for block in index["documents"][0]["blocks"]] == ["page-1", "page-2", "page-3"]
    assert "error" not in index["documents"][0]


def test_extract_tables_names_the_missing_dependency(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def without_pdfplumber(name, *args, **kwargs):
        if name == "pdfplumber":
            raise ImportError("No module named 'pdfplumber'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_pdfplumber)
    assert pdf_tables.available() is False
    with pytest.raises(RuntimeError, match="pip install pdfplumber"):
        pdf_tables.extract_tables(tmp_path / "any.pdf")


def test_a_table_extraction_failure_keeps_the_text_blocks(tmp_path, table_pdf, manifest_for, monkeypatch):
    def boom(path, first=None, last=None):
        raise ValueError("pdfplumber could not parse this file")

    monkeypatch.setattr(pdf_tables, "extract_tables", boom)
    cache_dir = tmp_path / ".document-reader"
    index = build_cache.build(manifest_for([table_pdf], cache_dir), cache_dir, window=500)

    assert [block["block_id"] for block in index["documents"][0]["blocks"]] == ["page-1", "page-2", "page-3"]


def test_normalize_turns_pdf_tables_into_table_blocks(table_pdf, tmp_path, monkeypatch, capsys):
    import normalize_output

    source = tmp_path / "reader.json"
    source.write_text(json.dumps(read_pdf.tables(table_pdf, None, 100)), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["normalize_output.py", str(source)])
    assert normalize_output.main() == 0
    result = json.loads(capsys.readouterr().out)

    assert [block["kind"] for block in result["blocks"]] == ["table", "table", "table"]
    first = result["blocks"][0]
    assert (first["source"]["page"], first["source"]["table"]) == (1, 1)
    assert first["data"]["headers"] == ["ID", "Rule", "Status"]
    assert first["data"]["rows"][0] == {"row": 2, "cells": ["R-1", "Lock after 5 attempts", "pending"]}
