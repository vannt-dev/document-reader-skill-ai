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
    assert auth["ref"]["lines"] == [4, 6]


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
