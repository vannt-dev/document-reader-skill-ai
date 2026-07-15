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
