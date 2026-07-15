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
    # The header row lives only in `headers`; `rows` holds data rows only.
    assert [r["cells"] for r in block["content"]["rows"]] == [
        ["REQ-1", "Login endpoint", "pending"],
        ["REQ-2", "Logout endpoint", "pending"],
    ]
    assert block["content"]["rows"][0]["row"] == 2


def test_build_excludes_header_from_every_split_block(tmp_path, manifest_for):
    from openpyxl import Workbook

    path = tmp_path / "big.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["ID", "Value"])
    for i in range(1, 6):  # rows 2..6 are data
        sheet.append([f"R{i}", i])
    workbook.save(path)

    cache_dir = tmp_path / ".document-reader"
    manifest_path = manifest_for([path], cache_dir)
    build_cache.build(manifest_path, cache_dir, window=2)  # force multiple blocks

    cached = json.loads((cache_dir / "cache" / "big-xlsx.json").read_text(encoding="utf-8"))
    assert len(cached["blocks"]) >= 2
    # No block contains the header row (row 1); every block carries headers separately.
    all_rows = [r["row"] for b in cached["blocks"] for r in b["content"]["rows"]]
    assert 1 not in all_rows
    assert all_rows == [2, 3, 4, 5, 6]
    for block in cached["blocks"]:
        assert block["content"]["headers"] == ["ID", "Value"]


def test_build_disambiguates_colliding_doc_ids(tmp_path, manifest_for):
    # "a-b.md" and "a_b.md" both slugify to "a-b-md".
    first = tmp_path / "a-b.md"
    first.write_text("# One\nalpha\n", encoding="utf-8")
    second = tmp_path / "a_b.md"
    second.write_text("# Two\nbeta\n", encoding="utf-8")

    cache_dir = tmp_path / ".document-reader"
    manifest_path = manifest_for([first, second], cache_dir)
    index = build_cache.build(manifest_path, cache_dir, window=500)

    doc_ids = [d["doc_id"] for d in index["documents"]]
    assert len(doc_ids) == len(set(doc_ids))  # unique despite slug collision
    assert "a-b-md" in doc_ids
    for doc_id in doc_ids:
        assert (cache_dir / "cache" / f"{doc_id}.json").is_file()


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
