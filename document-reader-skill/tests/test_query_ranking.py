import json
import subprocess
import sys
from pathlib import Path

import pytest

import query_cache

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _seed(cache_dir: Path, blocks, doc_id="doc"):
    (cache_dir / "cache").mkdir(parents=True, exist_ok=True)
    (cache_dir / "cache" / f"{doc_id}.json").write_text(json.dumps({"blocks": blocks}), encoding="utf-8")
    index = {"documents": [{"doc_id": doc_id, "path": f"{doc_id}.md", "sha256": "h"}]}
    (cache_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return cache_dir


def _block(block_id, label, *texts):
    content = {"text": texts[0]} if len(texts) == 1 else {"cells": list(texts)}
    return {"block_id": block_id, "ref": {}, "label": label, "content": content}


BLOCKS = [
    _block("b1", "Intro", "Users can reset a forgotten password by email."),
    _block("b2", "Audit", "Every login is recorded."),
    _block("b3", "Login", "The login form asks for a password; a wrong password locks after 5 tries."),
    _block("b4", "Notes", "password login rules are in the appendix"),
]


@pytest.fixture
def cache_dir(tmp_path):
    return _seed(tmp_path / ".document-reader", BLOCKS)


def ids(result):
    return [r["block_id"] for r in result["results"]]


def test_multi_word_query_matches_every_word_anywhere_in_the_block(cache_dir):
    # Old behaviour matched "login password" only as one phrase, which no block holds.
    assert ids(query_cache.query(cache_dir, keyword="login password")) == ["b3", "b4"]


def test_words_may_sit_in_different_cells_of_a_row(tmp_path):
    cache_dir = _seed(tmp_path / ".document-reader", [
        _block("r1", "API", "REQ-1", "Login endpoint", "pending"),
        _block("r2", "API", "REQ-2", "Logout endpoint", "done"),
    ])
    assert ids(query_cache.query(cache_dir, keyword="login pending")) == ["r1"]


def test_more_occurrences_rank_first_and_ties_keep_document_order(cache_dir):
    # b3 says "password" twice and "login" twice (once in its label), b4 each once.
    assert ids(query_cache.query(cache_dir, keyword="login password")) == ["b3", "b4"]
    # One occurrence each of "password": b1 and b4 tie, so document order decides.
    ranked = ids(query_cache.query(cache_dir, keyword="password"))
    assert ranked[0] == "b3"
    assert ranked[1:] == ["b1", "b4"]


def test_whole_phrase_ranks_above_scattered_words(tmp_path):
    cache_dir = _seed(tmp_path / ".document-reader", [
        _block("s1", "Reset", "A reset link is sent; the password must change."),
        _block("s2", "Reset", "Password reset needs the old password."),
        _block("s3", "Other", "See the password reset page."),
    ])
    result = query_cache.query(cache_dir, keyword="password reset", explain=True)
    assert ids(result) == ["s2", "s3", "s1"]
    assert [r["score"]["phrase"] for r in result["results"]] == [True, True, False]


def test_any_mode_weighs_rare_words_above_common_ones(cache_dir):
    result = query_cache.query(cache_dir, keyword="login email", match="any", explain=True)
    # No block holds both, so every hit has one word. "email" is in one block and "login" in
    # three, so the rarer word ranks b1 first; b3 says "login" twice, so it leads the rest.
    assert {r["score"]["words"] for r in result["results"]} == {1}
    assert ids(result) == ["b1", "b3", "b2", "b4"]


def test_any_mode_puts_blocks_with_all_words_above_the_rest(cache_dir):
    result = query_cache.query(cache_dir, keyword="forgotten password", match="any", explain=True)
    assert ids(result)[0] == "b1"
    assert result["results"][0]["score"]["words"] == 2
    assert all(r["score"]["words"] == 1 for r in result["results"][1:])


def test_phrase_mode_keeps_the_old_whole_phrase_matching(cache_dir):
    assert ids(query_cache.query(cache_dir, keyword="login password", match="phrase")) == []
    assert ids(query_cache.query(cache_dir, keyword="password login", match="phrase")) == ["b4"]


def test_doc_order_keeps_document_order(cache_dir):
    assert ids(query_cache.query(cache_dir, keyword="password", order="doc")) == ["b1", "b3", "b4"]


def test_limit_keeps_the_best_matches_and_reports_truncation(cache_dir):
    ranked = query_cache.query(cache_dir, keyword="password", max_results=1)
    assert ids(ranked) == ["b3"] and ranked["truncated"] is True
    in_order = query_cache.query(cache_dir, keyword="password", max_results=1, order="doc")
    assert ids(in_order) == ["b1"] and in_order["truncated"] is True
    assert query_cache.query(cache_dir, keyword="password", max_results=3)["truncated"] is False


def test_score_is_shown_only_when_asked(cache_dir):
    plain = query_cache.query(cache_dir, keyword="login password")
    assert all("score" not in r for r in plain["results"])
    explained = query_cache.query(cache_dir, keyword="login password", explain=True)
    first = explained["results"][0]["score"]
    assert first["words"] == 2 and first["phrase"] is False
    assert isinstance(first["weight"], float) and first["weight"] > 0


def test_filters_without_a_keyword_stay_in_document_order(cache_dir):
    assert ids(query_cache.query(cache_dir, doc="doc")) == ["b1", "b2", "b3", "b4"]


def test_multi_word_query_of_key_names_still_matches_nothing(cache_dir):
    assert ids(query_cache.query(cache_dir, keyword="text cells")) == []


def test_vietnamese_words_without_accents_match_and_rank(tmp_path):
    cache_dir = _seed(tmp_path / ".document-reader", [
        _block("v1", "Tổng quan", "Hệ thống đang chạy, người dùng chưa cần mật khẩu."),
        _block("v2", "Đăng nhập", "Người dùng đăng nhập bằng email và mật khẩu."),
        _block("v3", "Mật khẩu", "Mật khẩu tối thiểu 8 ký tự."),
    ])
    assert ids(query_cache.query(cache_dir, keyword="dang nhap mat khau")) == ["v2"]
    # v3 holds "Mật khẩu" in its label and its text; v1 and v2 once each, in document order.
    assert ids(query_cache.query(cache_dir, keyword="mat khau")) == ["v3", "v1", "v2"]
    # Typed with accents, each word must keep them: "đang" is not "đăng".
    assert ids(query_cache.query(cache_dir, keyword="đăng mật")) == ["v2"]
    assert ids(query_cache.query(cache_dir, keyword="đang mật")) == ["v1"]
    # Without accents, "dang" finds both "đang" and "đăng"; v2 also holds "nhap" and ranks first.
    assert ids(query_cache.query(cache_dir, keyword="dang nhap", match="any"))[0] == "v2"


def test_idf_is_computed_over_the_documents_searched(tmp_path):
    cache_dir = tmp_path / ".document-reader"
    _seed(cache_dir, [_block("a1", "A", "alpha beta")], doc_id="one")
    _seed(cache_dir, [_block("b1", "B", "alpha")], doc_id="two")
    index = {"documents": [{"doc_id": "one", "path": "one.md", "sha256": "h"},
                           {"doc_id": "two", "path": "two.md", "sha256": "h"}]}
    (cache_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    def weight(**filters):
        result = query_cache.query(cache_dir, keyword="alpha", explain=True, **filters)
        return result["results"][-1]["score"]["weight"]

    # "alpha" is in every block searched either way, but searching one document makes it
    # a word of one block out of one, not two out of two, which weighs it differently.
    assert ids(query_cache.query(cache_dir, keyword="alpha")) == ["a1", "b1"]
    assert weight(doc="two") != weight()


def _cli(*args):
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / "query_cache.py"), *args],
        capture_output=True, text=True, encoding="utf-8",
    )
    return completed


def test_cli_limit_order_match_and_explain(cache_dir):
    base = ["--cache-dir", str(cache_dir)]
    ranked = json.loads(_cli("password", "--limit", "2", *base).stdout)
    assert ids(ranked) == ["b3", "b1"] and ranked["truncated"] is True
    assert all("score" not in r for r in ranked["results"])
    assert ranked["query"]["match"] == "all" and ranked["query"]["order"] == "rank"
    in_order = json.loads(_cli("password", "--order", "doc", *base).stdout)
    assert ids(in_order) == ["b1", "b3", "b4"]
    phrase = json.loads(_cli("login password", "--match", "phrase", *base).stdout)
    assert ids(phrase) == []
    explained = json.loads(_cli("password login", "--explain", *base).stdout)
    assert explained["results"][0]["score"]["words"] == 2
    old_name = _cli("password", "--max-results", "1", *base)
    assert ids(json.loads(old_name.stdout)) == ["b3"]


def test_cli_rejects_ranking_options_with_changes(cache_dir):
    for extra in (["--order", "doc"], ["--match", "any"], ["--explain"]):
        completed = _cli("--changes", "--cache-dir", str(cache_dir), *extra)
        assert completed.returncode == 2, extra
        assert "--changes" in completed.stderr
