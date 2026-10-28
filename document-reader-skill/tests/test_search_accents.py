import json
import subprocess
import sys
from pathlib import Path

import pytest

import query_cache
from common import fold_text, text_matcher

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_fold_text_drops_accents_and_case_including_d_with_stroke():
    assert fold_text("Đăng NHẬP Tài Khoản") == "dang nhap tai khoan"
    assert fold_text("Crème brûlée") == "creme brulee"


@pytest.mark.parametrize("query, text, found", [
    ("dang nhap", "Người dùng Đăng nhập bằng mật khẩu", True),  # no accents typed: any accents match
    ("DANG NHAP", "đăng nhập", True),
    ("đăng nhập", "dang nhap", False),  # accents typed: they must be there
    ("đăng nhập", "ĐĂNG NHẬP", True),
    ("dang", "đang", True),
    ("đang", "đăng", False),
])
def test_text_matcher_ignores_accents_only_when_none_are_typed(query, text, found):
    assert bool(text_matcher(query)(text)) is found


def test_regex_and_case_sensitive_searches_are_unchanged():
    assert not text_matcher("dang", regex=True)("Đăng")
    assert not text_matcher("dang", case_sensitive=True)("Đăng")
    assert text_matcher("Đăng", case_sensitive=True)("Đăng nhập")


def test_search_document_finds_vietnamese_without_accents(tmp_path):
    doc = tmp_path / "notes.md"
    doc.write_text("# Yêu cầu\n\nNgười dùng đăng nhập bằng email.\nĐơn hàng được lưu.\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / "search_document.py"), str(doc), "dang nhap"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    assert [m["line"] for m in json.loads(completed.stdout)["matches"]] == [3]


def test_query_cache_keyword_ignores_accents_when_none_are_typed(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    (cache_dir / "cache").mkdir(parents=True)
    blocks = [{"block_id": "b1", "ref": {}, "label": "Đăng nhập", "content": {"text": "Mật khẩu tối thiểu 8 ký tự"}},
              {"block_id": "b2", "ref": {}, "label": "Đơn hàng", "content": {"text": "Lưu đơn"}}]
    (cache_dir / "cache" / "doc.json").write_text(json.dumps({"blocks": blocks}), encoding="utf-8")
    (cache_dir / "index.json").write_text(json.dumps({"documents": [{"doc_id": "doc", "path": "doc.md", "sha256": "h"}]}),
                                          encoding="utf-8")
    hit = lambda word: [r["block_id"] for r in query_cache.query(cache_dir, keyword=word)["results"]]
    assert hit("mat khau") == ["b1"]
    assert hit("dang nhap") == ["b1"]
    assert hit("don") == ["b2"]
    assert hit("đơn") == ["b2"]
    assert hit("dơn") == []


def test_query_cache_label_filter_ignores_accents_when_none_are_typed(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    (cache_dir / "cache").mkdir(parents=True)
    blocks = [{"block_id": "b1", "ref": {}, "label": "Đăng nhập", "content": {"text": "x"}},
              {"block_id": "b2", "ref": {}, "label": "Đơn hàng", "content": {"text": "y"}}]
    (cache_dir / "cache" / "doc.json").write_text(json.dumps({"blocks": blocks}), encoding="utf-8")
    (cache_dir / "index.json").write_text(json.dumps({"documents": [{"doc_id": "doc", "path": "doc.md", "sha256": "h"}]}),
                                          encoding="utf-8")
    assert [r["block_id"] for r in query_cache.query(cache_dir, label="dang nhap")["results"]] == ["b1"]
