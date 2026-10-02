import json
import zipfile

import pytest

import build_cache
import csv_text
import doc_text
import index_documents
import query_cache
import read_csv
import read_pptx
from conftest import pptx_shape, write_pptx


# --- .pptx -----------------------------------------------------------------


def test_pptx_slides_follow_presentation_order_not_part_names(sample_pptx):
    slides = doc_text.pptx_slides(sample_pptx)

    assert [(slide["slide"], slide["title"]) for slide in slides] == [
        (1, "Project kickoff"),
        (2, "Authentication"),
        (3, None),
    ]
    assert slides[0]["lines"] == ["Q3 planning"]
    assert slides[1]["lines"] == [
        "Users must log in.",
        "Sessions expire after 30 minutes.",
        "ID | Rule",
        "R-1 | Lock after 5 attempts",
    ]
    # The slide-number placeholder of the notes page is not part of the notes.
    assert slides[1]["notes"] == ["Mention the audit finding."]
    assert slides[2]["lines"] == ["No title on this slide, only a text box."]
    assert slides[2]["notes"] == []


def test_pptx_reads_grouped_shapes_and_strict_open_xml(tmp_path):
    grouped = "<p:grpSp>" + pptx_shape("Inside a group") + "</p:grpSp>"
    path = write_pptx(
        tmp_path / "strict.pptx",
        [(pptx_shape("Strict deck", "title") + grouped, None)],
        p_ns="http://purl.oclc.org/ooxml/presentationml/main",
        a_ns="http://purl.oclc.org/ooxml/drawingml/main",
        r_ns="http://purl.oclc.org/ooxml/officeDocument/relationships",
    )

    slides = doc_text.pptx_slides(path)
    assert [(slide["title"], slide["lines"]) for slide in slides] == [("Strict deck", ["Inside a group"])]


def test_pptx_rejects_legacy_ppt_and_a_zip_that_is_not_a_deck(tmp_path):
    legacy = tmp_path / "old.pptx"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0 not a zip")
    with pytest.raises(ValueError, match="legacy .ppt"):
        doc_text.pptx_slides(legacy)

    other = tmp_path / "other.pptx"
    with zipfile.ZipFile(other, "w") as archive:
        archive.writestr("word/document.xml", "<x/>")
    with pytest.raises(ValueError, match="presentation.xml is missing"):
        doc_text.pptx_slides(other)


def test_read_pptx_outline_and_slide_range(sample_pptx):
    outline = read_pptx.outline(sample_pptx)
    assert outline["slide_count"] == 3
    assert outline["outline"][1] == {"slide": 2, "title": "Authentication", "lines": 4, "has_notes": True}

    everything = read_pptx.read(sample_pptx, None, 12000)
    assert everything["source"] == {"start_slide": 1, "end_slide": 3}
    assert everything["content"].startswith("--- slide 1 ---\n# Project kickoff\nQ3 planning")
    assert "Notes:\nMention the audit finding." in everything["content"]

    second = read_pptx.read(sample_pptx, "2", 12000, include_notes=False)
    assert second["source"] == {"start_slide": 2, "end_slide": 2}
    assert second["content"].splitlines()[:2] == ["--- slide 2 ---", "# Authentication"]
    assert "Notes:" not in second["content"]
    assert "kickoff" not in second["content"]

    assert read_pptx.read(sample_pptx, None, 20)["truncated"] is True


def test_parse_slides_validates_the_range():
    assert read_pptx.parse_slides(None, 5) == (1, 5)
    assert read_pptx.parse_slides("2-9", 5) == (2, 5)
    for bad in ("0", "4-2", "x", "6"):
        with pytest.raises(ValueError):
            read_pptx.parse_slides(bad, 5)


def test_read_pptx_on_an_empty_deck(tmp_path):
    path = write_pptx(tmp_path / "empty.pptx", [])

    assert read_pptx.outline(path)["slide_count"] == 0
    assert read_pptx.read(path, None, 100)["content"] == ""


# --- .csv ------------------------------------------------------------------


def test_csv_detects_the_delimiter_and_keeps_quoted_cells_whole(sample_csv):
    delimiter, rows = csv_text.csv_rows(sample_csv)

    assert delimiter == ";"
    assert list(rows) == [
        (1, ["ID", "Requirement", "Status"]),
        (2, ["REQ-1", "Login; with MFA", "pending"]),
        (3, ["REQ-2", "Logout endpoint", "done"]),
        (4, ["REQ-3", "Password\nreset", "pending"]),
    ]


def test_csv_reads_tsv_and_falls_back_from_utf8(tmp_path):
    tsv = tmp_path / "data.tsv"
    tsv.write_text("a\tb,c\n1\t2\n", encoding="utf-8")
    delimiter, rows = csv_text.csv_rows(tsv)
    assert delimiter == "\t"
    assert list(rows)[0] == (1, ["a", "b,c"])

    latin = tmp_path / "latin.csv"
    latin.write_bytes("name,city\nRen\xe9,Montr\xe9al\n".encode("cp1252"))
    assert list(csv_text.csv_rows(latin)[1])[1] == (2, ["René", "Montréal"])

    single = tmp_path / "single.csv"
    single.write_text("just one column\nvalue\n", encoding="utf-8")
    assert csv_text.csv_rows(single)[0] == ","


def test_read_csv_outline_range_and_filters(sample_csv):
    outline = read_csv.outline(sample_csv, preview_rows=2)
    assert (outline["rows"], outline["columns"], outline["delimiter"]) == (4, 3, ";")
    assert outline["preview"] == [["ID", "Requirement", "Status"], ["REQ-1", "Login; with MFA", "pending"]]

    everything = read_csv.read(sample_csv, None, None, {}, 100, 50)
    assert everything["headers"] == ["ID", "Requirement", "Status"]
    assert [row["row"] for row in everything["rows"]] == [1, 2, 3, 4]
    assert everything["truncated"] is False

    ranged = read_csv.read(sample_csv, 3, 3, {}, 100, 50)
    assert ranged["rows"] == [{"row": 3, "cells": ["REQ-2", "Logout endpoint", "done"]}]
    assert ranged["headers"] == ["ID", "Requirement", "Status"]

    pending = read_csv.read(sample_csv, 2, None, {"Status": "pending"}, 100, 50)
    assert [row["cells"][0] for row in pending["rows"]] == ["REQ-1", "REQ-3"]

    limited = read_csv.read(sample_csv, None, None, {}, 2, 2)
    assert limited["truncated"] is True
    assert limited["rows"][1]["cells"] == ["REQ-1", "Login; with MFA"]

    with pytest.raises(ValueError, match="Filter headers not found"):
        read_csv.read(sample_csv, None, None, {"Owner": "x"}, 100, 50)


# --- index, cache, query ---------------------------------------------------


def test_index_metadata_for_pptx_and_csv(sample_pptx, sample_csv):
    deck = index_documents.pptx_metadata(sample_pptx, 2)
    assert deck["slide_count"] == 3
    assert deck["slides"] == [
        {"slide": 1, "title": "Project kickoff"},
        {"slide": 2, "title": "Authentication"},
    ]
    assert deck["slides_truncated"] is True

    table = index_documents.csv_metadata(sample_csv, 1, 20)
    assert table == {
        "delimiter": ";", "rows": 4, "columns": 3,
        "preview": [["ID", "Requirement", "Status"]], "preview_truncated_columns": False,
    }


def test_build_cache_extracts_slides_and_query_finds_notes(tmp_path, sample_pptx, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    index = build_cache.build(manifest_for([sample_pptx], cache_dir), cache_dir, window=500)

    document = index["documents"][0]
    assert document["type"] == "pptx"
    assert [(block["block_id"], block["label"]) for block in document["blocks"]] == [
        ("slide-1", "Project kickoff"), ("slide-2", "Authentication"), ("slide-3", "Slide 3"),
    ]
    result = query_cache.query(cache_dir, keyword="audit finding")
    assert [(r["block_id"], r["ref"]) for r in result["results"]] == [
        ("slide-2", {"slide": 2, "title": "Authentication"}),
    ]


def test_build_cache_extracts_csv_like_a_sheet(tmp_path, sample_csv, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    index = build_cache.build(manifest_for([sample_csv], cache_dir), cache_dir, window=2)

    document = index["documents"][0]
    assert document["type"] == "csv"
    assert [block["block_id"] for block in document["blocks"]] == ["rows!A1:C2", "rows!A3:C4"]

    cached = json.loads((cache_dir / "cache" / "rules-csv.json").read_text(encoding="utf-8"))
    first, second = cached["blocks"]
    assert first["content"]["headers"] == ["ID", "Requirement", "Status"]
    # The header row lives only in `headers`, as it does for Excel.
    assert [row["row"] for row in first["content"]["rows"]] == [2]
    assert [row["cells"][0] for row in second["content"]["rows"]] == ["REQ-2", "REQ-3"]


def test_normalize_accepts_pptx_and_csv_reader_output(sample_pptx, sample_csv, tmp_path, monkeypatch, capsys):
    import normalize_output

    def normalize(payload):
        source = tmp_path / "reader.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["normalize_output.py", str(source)])
        assert normalize_output.main() == 0
        return json.loads(capsys.readouterr().out)

    assert normalize(read_pptx.read(sample_pptx, "2", 12000))["blocks"][0]["kind"] == "text"
    assert normalize(read_pptx.outline(sample_pptx))["blocks"][0]["kind"] == "structure"
    table = normalize(read_csv.read(sample_csv, None, None, {}, 100, 50))
    assert table["documents"][0]["type"] == "csv"
    assert table["blocks"][0]["kind"] == "table"
    assert normalize(read_csv.outline(sample_csv))["blocks"][0]["data"]["rows"] == 4
