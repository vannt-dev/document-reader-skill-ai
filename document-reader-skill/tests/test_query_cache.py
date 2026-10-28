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


def test_query_truncates_only_when_extra_match_exists(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    _seed(cache_dir)
    full = query_cache.query(cache_dir, keyword="users", max_results=2)
    assert len(full["results"]) == 2
    assert full["truncated"] is False
    capped = query_cache.query(cache_dir, keyword="users", max_results=1)
    assert len(capped["results"]) == 1
    assert capped["truncated"] is True


def test_query_skips_corrupt_cache_file(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    _seed(cache_dir)
    # Corrupt one document's cache file; the query must not crash.
    (cache_dir / "cache" / "api-md.json").write_text("{ not valid json", encoding="utf-8")
    result = query_cache.query(cache_dir, keyword="users")
    assert result["results"] == []
    assert any("api-md" in w for w in result["warnings"])


def test_query_reports_corrupt_index(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    _seed(cache_dir)
    (cache_dir / "index.json").write_text("{ broken", encoding="utf-8")
    result = query_cache.query(cache_dir, keyword="users")
    assert result["results"] == []
    assert any("index.json" in w for w in result["warnings"])


def _seed_blocks(cache_dir: Path, blocks):
    (cache_dir / "cache").mkdir(parents=True, exist_ok=True)
    payload = {"doc_id": "doc", "path": "doc.xlsx", "sha256": "h", "type": "excel", "blocks": blocks}
    (cache_dir / "cache" / "doc.json").write_text(json.dumps(payload), encoding="utf-8")
    index = {"schema_version": "1.0", "documents": [{
        "doc_id": "doc", "path": "doc.xlsx", "sha256": "h", "type": "excel",
        "blocks": [{"block_id": b["block_id"], "label": b["label"]} for b in blocks],
    }]}
    (cache_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")


def test_query_keyword_does_not_match_key_names(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    _seed(cache_dir)
    for word in ("text", "content", '"'):
        assert query_cache.query(cache_dir, keyword=word)["results"] == [], word


def test_query_keyword_matches_quotes_and_line_breaks_as_written(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    _seed_blocks(cache_dir, [{"block_id": "b1", "ref": {}, "label": "Note",
                              "content": {"text": 'Click "Save"\nthen close the dialog'}}])
    for word in ('"save"', 'save"\nthen', "\\"):
        found = [r["block_id"] for r in query_cache.query(cache_dir, keyword=word)["results"]]
        assert found == ([] if word == "\\" else ["b1"]), word


def test_query_keyword_searches_table_cells_not_their_keys(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    _seed_blocks(cache_dir, [{"block_id": "Sheet1!A1:B3", "ref": {"sheet": "Sheet1"}, "label": "Sheet1",
                              "content": {"headers": ["Name", "Price"],
                                          "rows": [{"row": 2, "cells": ["Apple", 1.5]},
                                                   {"row": 3, "cells": ["Pear", None]}]}}])
    hit = lambda word: [r["block_id"] for r in query_cache.query(cache_dir, keyword=word)["results"]]
    assert hit("pear") == ["Sheet1!A1:B3"]
    assert hit("price") == ["Sheet1!A1:B3"]
    assert hit("1.5") == ["Sheet1!A1:B3"]
    for word in ("cells", "rows", "headers", "null", "row"):
        assert hit(word) == [], word
