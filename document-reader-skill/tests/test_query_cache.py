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
