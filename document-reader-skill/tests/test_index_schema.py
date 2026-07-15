import json
from pathlib import Path

import build_cache

SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "document-cache.schema.json"
CACHE_FILE_SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "document-cache-file.schema.json"


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


def test_cache_file_schema_is_valid_json():
    data = json.loads(CACHE_FILE_SCHEMA.read_text(encoding="utf-8"))
    assert data["title"] == "Document Reader Cache File"


def test_built_cache_file_matches_schema_required_keys(tmp_path, sample_md, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    manifest_path = manifest_for([sample_md], cache_dir)
    build_cache.build(manifest_path, cache_dir, window=500)

    schema = json.loads(CACHE_FILE_SCHEMA.read_text(encoding="utf-8"))
    doc_required = schema["required"]
    block_required = schema["properties"]["blocks"]["items"]["required"]
    payload = json.loads((cache_dir / "cache" / "business-md.json").read_text(encoding="utf-8"))
    assert all(key in payload for key in doc_required)
    for block in payload["blocks"]:
        assert all(key in block for key in block_required)
