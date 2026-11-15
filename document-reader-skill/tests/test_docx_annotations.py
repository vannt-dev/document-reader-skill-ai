"""Comments and tracked changes in .docx files."""

import json
import os
import subprocess
import sys
from pathlib import Path

import build_cache
import doc_text
import query_cache
import read_docx
from conftest import W_NS, docx_paragraph, write_docx

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
W15_NS = "http://schemas.microsoft.com/office/word/2012/wordml"
HEADING_STYLE = '<w:style w:type="paragraph" w:styleId="H1"><w:name w:val="heading 1"/></w:style>'


def comment(comment_id, author, date, text, para_id):
    return (
        f'<w:comment w:id="{comment_id}" w:author="{author}" w:date="{date}" w:initials="X">'
        f'<w:p w14:paraId="{para_id}"><w:r><w:t>{text}</w:t></w:r></w:p></w:comment>'
    )


def comments_part(*comments):
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><w:comments xmlns:w="{W_NS}" xmlns:w14="{W14_NS}">'
        + "".join(comments) + "</w:comments>"
    )


def extended_part(*entries):
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><w15:commentsEx xmlns:w15="{W15_NS}">'
        + "".join(entries) + "</w15:commentsEx>"
    )


def run(text, tag="t"):
    return f"<w:r><w:{tag}>{text}</w:{tag}></w:r>"


def revision(kind, author, date, inner, revision_id=1):
    return f'<w:{kind} w:id="{revision_id}" w:author="{author}" w:date="{date}">{inner}</w:{kind}>'


def reference(comment_id):
    return f'<w:r><w:commentReference w:id="{comment_id}"/></w:r>'


def reviewed_docx(tmp_path):
    """A spec with a comment and its reply, a comment across two paragraphs, an
    insertion, a deletion in a table cell, a deleted paragraph and a move."""
    table = (
        "<w:tbl>"
        "<w:tr><w:tc><w:p>" + run("ID") + "</w:p></w:tc><w:tc><w:p>" + run("Rule") + "</w:p></w:tc></w:tr>"
        "<w:tr><w:tc><w:p>" + run("REQ-1") + "</w:p></w:tc><w:tc><w:p>"
        + run("Lock after ")
        + revision("del", "Bình", "2026-10-02T09:00:00Z", run("3", "delText"), 4)
        + revision("ins", "Bình", "2026-10-02T09:00:00Z", run("5"), 5)
        + run(" attempts") + "</w:p></w:tc></w:tr>"
        "</w:tbl>"
    )
    body = "".join([
        docx_paragraph("Login", "H1"),
        "<w:p>" + run("Users ")
        + '<w:commentRangeStart w:id="0"/>' + run("must log in")
        + '<w:commentRangeStart w:id="1"/><w:commentRangeEnd w:id="0"/>' + reference("0")
        + '<w:commentRangeEnd w:id="1"/>' + reference("1")
        + revision("ins", "Lan", "2026-10-01T08:00:00Z", run(" with MFA"), 2)
        + run(".") + "</w:p>",
        "<w:p>" + revision("del", "Lan", "2026-10-01T08:05:00Z", run("Passwords never expire.", "delText"), 3) + "</w:p>",
        "<w:p>" + '<w:commentRangeStart w:id="2"/>' + run("Sessions end") + "</w:p>",
        "<w:p>" + run("after 30 minutes") + '<w:commentRangeEnd w:id="2"/>' + reference("2") + "</w:p>",
        table,
        "<w:p>" + revision("moveFrom", "Lan", "2026-10-03T10:00:00Z", run("Audit everything. "), 6)
        + run("Logs are kept.") + revision("moveTo", "Lan", "2026-10-03T10:00:00Z", run(" Audit everything."), 7)
        + "</w:p>",
    ])
    parts = {
        "word/comments.xml": comments_part(
            comment("0", "Nguyễn Văn An", "2026-10-01T07:00:00Z", "Which roles?", "1A2B0001"),
            comment("1", "Lan", "2026-10-01T07:30:00Z", "All of them.", "1A2B0002"),
            comment("2", "An", "2026-10-01T07:45:00Z", "Idle or absolute?", "1A2B0003"),
        ),
        "word/commentsExtended.xml": extended_part(
            '<w15:commentEx w15:paraId="1A2B0001" w15:done="1"/>',
            '<w15:commentEx w15:paraId="1A2B0002" w15:paraIdParent="1A2B0001" w15:done="1"/>',
            '<w15:commentEx w15:paraId="1A2B0003" w15:done="0"/>',
        ),
    }
    return write_docx(tmp_path / "reviewed.docx", body, HEADING_STYLE, parts)


# --- items -----------------------------------------------------------------


def test_text_is_the_document_with_every_change_accepted(tmp_path):
    items = doc_text.docx_items(reviewed_docx(tmp_path))

    assert [item["text"] for item in items] == [
        "Login",
        "Users must log in with MFA.",
        "Sessions end",
        "after 30 minutes",
        "ID | Rule",
        "REQ-1 | Lock after 5 attempts",
        "Logs are kept. Audit everything.",
    ]


def test_comment_carries_its_anchor_author_date_and_nested_reply(tmp_path):
    items = doc_text.docx_items(reviewed_docx(tmp_path))

    assert items[1]["comments"] == [{
        "id": "0", "author": "Nguyễn Văn An", "date": "2026-10-01T07:00:00Z", "text": "Which roles?",
        "anchor": "must log in", "resolved": True,
        "replies": [{"id": "1", "author": "Lan", "date": "2026-10-01T07:30:00Z", "text": "All of them.",
                     "resolved": True}],
    }]


def test_comment_across_two_paragraphs_belongs_to_the_first(tmp_path):
    items = doc_text.docx_items(reviewed_docx(tmp_path))

    assert items[2]["comments"] == [{
        "id": "2", "author": "An", "date": "2026-10-01T07:45:00Z", "text": "Idle or absolute?",
        "anchor": "Sessions end\nafter 30 minutes",
    }]
    assert "comments" not in items[3]


def test_insertion_is_marked_and_listed(tmp_path):
    items = doc_text.docx_items(reviewed_docx(tmp_path))

    assert items[1]["revisions"][0] == {
        "type": "inserted", "text": " with MFA", "author": "Lan", "date": "2026-10-01T08:00:00Z",
    }
    assert items[1]["marked"].startswith("Users must log in{++ with MFA++}.")


def test_deleted_paragraph_keeps_numbering_and_moves_to_the_item_before(tmp_path):
    items = doc_text.docx_items(reviewed_docx(tmp_path))

    # Paragraph numbers follow the accepted document: the deleted paragraph has none.
    assert items[2]["index"] == 3 and items[2]["text"] == "Sessions end"
    assert items[1]["revisions"][1] == {
        "type": "deleted", "text": "Passwords never expire.", "author": "Lan", "date": "2026-10-01T08:05:00Z",
    }
    assert items[1]["marked"] == "Users must log in{++ with MFA++}.\n{--Passwords never expire.--}"


def test_deletion_inside_a_table_cell_lands_on_its_row(tmp_path):
    row = doc_text.docx_items(reviewed_docx(tmp_path))[5]

    assert row["kind"] == "table_row"
    assert row["marked"] == "REQ-1 | Lock after {--3--}{++5++} attempts"
    assert [(r["type"], r["text"], r["author"]) for r in row["revisions"]] == [
        ("deleted", "3", "Bình"), ("inserted", "5", "Bình"),
    ]


def test_move_counts_once_at_its_new_place(tmp_path):
    item = doc_text.docx_items(reviewed_docx(tmp_path))[6]

    assert item["marked"] == "{--Audit everything. --}Logs are kept.{++ Audit everything.++}"
    assert [r["type"] for r in item["revisions"]] == ["moved_from", "moved_to"]


def test_deleted_paragraph_before_any_text_goes_to_the_first_item(tmp_path):
    body = (
        "<w:p>" + revision("del", "Lan", "2026-10-01T08:00:00Z", run("Draft", "delText")) + "</w:p>"
        + docx_paragraph("Scope")
    )
    items = doc_text.docx_items(write_docx(tmp_path / "lead.docx", body))

    assert [item["text"] for item in items] == ["Scope"]
    assert items[0]["marked"] == "{--Draft--}\nScope"


def test_comment_on_text_that_was_then_replaced_anchors_to_the_deleted_text(tmp_path):
    # How Word saves a commented word replaced with tracking on: the insertion lands
    # before the comment range, which then holds only the deletion.
    body = (
        "<w:p>" + run("Links expire after ")
        + revision("ins", "Lan", "2026-10-01T08:00:00Z", run("15 minutes"), 1)
        + '<w:commentRangeStart w:id="0"/>'
        + revision("del", "Lan", "2026-10-01T08:00:00Z", run("30 minutes", "delText"), 2)
        + '<w:commentRangeEnd w:id="0"/>' + reference("0") + run(".") + "</w:p>"
    )
    parts = {"word/comments.xml": comments_part(
        comment("0", "An", "2026-10-01T07:00:00Z", "From when?", "1A2B0001"))}
    items = doc_text.docx_items(write_docx(tmp_path / "replaced.docx", body, "", parts))

    assert items[0]["text"] == "Links expire after 15 minutes."
    assert items[0]["comments"] == [{
        "id": "0", "author": "An", "date": "2026-10-01T07:00:00Z", "text": "From when?",
        "anchor": "30 minutes", "anchor_deleted": True,
    }]


def test_comment_over_kept_and_deleted_text_anchors_to_the_kept_text(tmp_path):
    body = (
        "<w:p>" + '<w:commentRangeStart w:id="0"/>' + run("Lock after ")
        + revision("del", "Lan", "2026-10-01T08:00:00Z", run("3", "delText"), 1)
        + revision("ins", "Lan", "2026-10-01T08:00:00Z", run("5"), 2)
        + '<w:commentRangeEnd w:id="0"/>' + reference("0") + "</w:p>"
    )
    parts = {"word/comments.xml": comments_part(
        comment("0", "An", "2026-10-01T07:00:00Z", "Why 5?", "1A2B0001"))}
    items = doc_text.docx_items(write_docx(tmp_path / "mixed.docx", body, "", parts))

    assert items[0]["comments"][0]["anchor"] == "Lock after 5"
    assert "anchor_deleted" not in items[0]["comments"][0]


def test_document_without_comments_or_changes_has_no_new_keys(sample_docx):
    items = doc_text.docx_items(sample_docx)

    assert all(set(item) == {"kind", "level", "text", "index"} for item in items)
    assert doc_text.docx_annotations(items) == {}


# --- cache blocks ------------------------------------------------------------


def test_cache_block_holds_comments_and_changes_with_paragraph_numbers(tmp_path):
    blocks = build_cache.extract_docx(reviewed_docx(tmp_path))

    login = blocks[0]["content"]
    assert login["text"].splitlines()[1] == "Users must log in with MFA."
    assert login["tracked_text"].splitlines()[1:3] == [
        "Users must log in{++ with MFA++}.", "{--Passwords never expire.--}",
    ]
    assert [(c["paragraph"], c["id"]) for c in login["comments"]] == [(2, "0"), (3, "2")]
    assert [(r["paragraph"], r["type"], r["text"]) for r in login["revisions"]][:3] == [
        (2, "inserted", " with MFA"), (2, "deleted", "Passwords never expire."), (6, "deleted", "3"),
    ]


def test_cache_block_of_a_plain_document_is_unchanged(sample_docx):
    for block in build_cache.extract_docx(sample_docx):
        assert set(block["content"]) == {"text"}


def test_comment_text_is_searchable_but_tracked_text_is_not_counted_twice(tmp_path):
    cache_dir = tmp_path / "cache-dir"
    (cache_dir / "cache").mkdir(parents=True)
    blocks = build_cache.extract_docx(reviewed_docx(tmp_path))
    (cache_dir / "cache" / "spec.json").write_text(json.dumps({"blocks": blocks}), encoding="utf-8")
    index = {"documents": [{"doc_id": "spec", "path": "reviewed.docx", "sha256": "h"}]}
    (cache_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")

    found = query_cache.query(cache_dir, "absolute", explain=True)["results"]
    assert [r["block_id"] for r in found] == [blocks[0]["block_id"]]
    assert query_cache.query(cache_dir, "2026-10-01T07")["results"] == []
    assert query_cache._text_values({"text": "a", "tracked_text": "a{++b++}"}) == ["a"]


# --- read_docx -----------------------------------------------------------------


def test_read_docx_lists_comments_and_changes_of_the_range(tmp_path):
    path = reviewed_docx(tmp_path)

    result = read_docx.read(path, None, 3, 4, 12000)
    assert result["content"] == "Sessions end\nafter 30 minutes"
    assert [c["id"] for c in result["comments"]] == ["2"]
    assert "revisions" not in result

    marked = read_docx.read(path, None, 6, 6, 12000, show_changes=True)
    assert marked["content"] == "REQ-1 | Lock after {--3--}{++5++} attempts"
    assert [r["text"] for r in marked["revisions"]] == ["3", "5"]

    outline = read_docx.outline(path)
    assert (outline["comment_count"], outline["revision_count"]) == (2, 6)


def test_read_docx_output_of_a_plain_document_is_unchanged(sample_docx):
    assert set(read_docx.read(sample_docx, None, None, None, 12000)) == {
        "document", "type", "source", "content", "truncated",
    }
    assert set(read_docx.outline(sample_docx)) == {"document", "type", "paragraph_count", "table_rows", "outline"}


def test_command_line_prints_vietnamese_authors_on_a_non_utf8_console(tmp_path):
    env = {name: value for name, value in os.environ.items() if name != "PYTHONIOENCODING"}
    env["PYTHONUTF8"] = "0"
    completed = subprocess.run(
        [sys.executable, "-X", "utf8=0", str(SCRIPTS / "read_docx.py"), str(reviewed_docx(tmp_path)),
         "--heading", "Login", "--show-changes"],
        capture_output=True, env=env,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.decode("utf-8"))
    assert result["comments"][0]["author"] == "Nguyễn Văn An"
    assert "{--3--}{++5++}" in result["content"]


def test_normalize_keeps_comments_and_changes_as_their_own_blocks(tmp_path, monkeypatch, capsys):
    import normalize_output

    source = tmp_path / "reader.json"
    source.write_text(json.dumps(read_docx.read(reviewed_docx(tmp_path), "Login", None, None, 12000)),
                      encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["normalize_output.py", str(source)])
    assert normalize_output.main() == 0
    blocks = json.loads(capsys.readouterr().out)["blocks"]

    assert [(block["kind"], block["source"].get("part")) for block in blocks] == [
        ("text", None), ("structure", "comments"), ("structure", "revisions"),
    ]
    assert blocks[1]["data"][0]["anchor"] == "must log in"


# --- read_docx --comments ------------------------------------------------------


def threads_docx(tmp_path, extended=True):
    """Four threads: a resolved one, an open one with two replies (one of them marked
    done), a resolved one whose reply is not marked done, and an open one under a
    second heading. Without `extended` the file has no commentsExtended.xml."""
    def commented(text, *ids):
        return "<w:p>" + run(text) + "".join(reference(comment_id) for comment_id in ids) + "</w:p>"

    body = "".join([
        docx_paragraph("Login", "H1"),
        commented("Users must log in.", "0"),
        commented("Sessions end after 30 minutes.", "1", "2", "3"),
        commented("Passwords expire.", "4", "5"),
        docx_paragraph("Audit", "H1"),
        commented("Logs are kept.", "6"),
    ])
    parts = {
        "word/comments.xml": comments_part(
            comment("0", "An", "2026-10-01T07:00:00Z", "Which roles?", "0A000000"),
            comment("1", "An", "2026-10-01T07:10:00Z", "Idle or absolute?", "0A000001"),
            comment("2", "Lan", "2026-10-01T07:20:00Z", "Idle.", "0A000002"),
            comment("3", "An", "2026-10-01T07:30:00Z", "Then say so.", "0A000003"),
            comment("4", "Bình", "2026-10-01T07:40:00Z", "How often?", "0A000004"),
            comment("5", "Lan", "2026-10-01T07:50:00Z", "Every 90 days.", "0A000005"),
            comment("6", "Bình", "2026-10-01T08:00:00Z", "For how long?", "0A000006"),
        ),
    }
    if extended:
        parts["word/commentsExtended.xml"] = extended_part(
            '<w15:commentEx w15:paraId="0A000000" w15:done="1"/>',
            '<w15:commentEx w15:paraId="0A000001" w15:done="0"/>',
            '<w15:commentEx w15:paraId="0A000002" w15:paraIdParent="0A000001" w15:done="1"/>',
            '<w15:commentEx w15:paraId="0A000003" w15:paraIdParent="0A000001" w15:done="0"/>',
            '<w15:commentEx w15:paraId="0A000004" w15:done="1"/>',
            '<w15:commentEx w15:paraId="0A000005" w15:paraIdParent="0A000004" w15:done="0"/>',
            '<w15:commentEx w15:paraId="0A000006" w15:done="0"/>',
        )
    return write_docx(tmp_path / "threads.docx", body, HEADING_STYLE, parts)


def test_comments_mode_lists_every_thread_with_its_resolved_state(tmp_path):
    result = read_docx.comments(threads_docx(tmp_path), None, None, None)

    assert set(result) == {"document", "type", "source", "summary", "thread_count", "open_count", "comments"}
    assert result["summary"] == "2 open of 4 threads"
    assert (result["thread_count"], result["open_count"]) == (4, 2)
    assert [(c["id"], c["paragraph"], c["resolved"]) for c in result["comments"]] == [
        ("0", 2, True), ("1", 3, False), ("4", 4, True), ("6", 6, False),
    ]


def test_unresolved_keeps_an_open_thread_with_its_replies_under_it(tmp_path):
    result = read_docx.comments(threads_docx(tmp_path), None, None, None, unresolved_only=True)

    assert result["unresolved_only"] is True
    assert result["summary"] == "2 open of 4 threads"
    assert result["comments"] == [
        {
            "paragraph": 3, "id": "1", "author": "An", "date": "2026-10-01T07:10:00Z",
            "text": "Idle or absolute?", "anchor": "", "resolved": False,
            # A reply marked done does not close the thread, and carries no state of its own.
            "replies": [
                {"id": "2", "author": "Lan", "date": "2026-10-01T07:20:00Z", "text": "Idle."},
                {"id": "3", "author": "An", "date": "2026-10-01T07:30:00Z", "text": "Then say so."},
            ],
        },
        {
            "paragraph": 6, "id": "6", "author": "Bình", "date": "2026-10-01T08:00:00Z",
            "text": "For how long?", "anchor": "", "resolved": False,
        },
    ]


def test_reply_to_a_resolved_thread_is_not_an_open_thread(tmp_path):
    path = threads_docx(tmp_path)

    everything = read_docx.comments(path, None, None, None)["comments"]
    assert everything[2]["resolved"] is True
    assert [reply["id"] for reply in everything[2]["replies"]] == ["5"]

    listed = read_docx.comments(path, None, None, None, unresolved_only=True)["comments"]
    assert all(c["id"] not in ("4", "5") for c in listed)
    assert all(reply["id"] != "5" for c in listed for reply in c.get("replies", []))


def test_comments_mode_counts_only_the_heading_or_range_asked_for(tmp_path):
    path = threads_docx(tmp_path)

    section = read_docx.comments(path, "login", None, None, unresolved_only=True)
    assert section["source"] == {
        "heading": {"title": "Login", "level": 1}, "start_paragraph": 1, "end_paragraph": 4,
    }
    assert section["summary"] == "1 open of 3 threads"
    assert [c["id"] for c in section["comments"]] == ["1"]

    one = read_docx.comments(path, None, 2, 2, unresolved_only=True)
    assert (one["summary"], one["comments"]) == ("0 open of 1 thread", [])


def test_file_without_resolved_state_lists_every_comment_as_open_and_says_so_once(tmp_path):
    result = read_docx.comments(threads_docx(tmp_path, extended=False), None, None, None, unresolved_only=True)

    assert result["summary"] == "7 open of 7 threads"
    assert [c["id"] for c in result["comments"]] == ["0", "1", "2", "3", "4", "5", "6"]
    assert all(c["resolved"] is False and "replies" not in c for c in result["comments"])
    assert "commentsExtended.xml" in result["note"]
    assert "note" not in read_docx.comments(threads_docx(tmp_path), None, None, None)


def test_comments_mode_on_a_document_without_comments(sample_docx):
    result = read_docx.comments(sample_docx, None, None, None, unresolved_only=True)

    assert (result["summary"], result["comments"]) == ("0 open of 0 threads", [])
    assert "note" not in result


def test_comments_mode_leaves_the_plain_read_as_it_was(tmp_path):
    result = read_docx.read(threads_docx(tmp_path), None, None, None, 12000)

    assert set(result) == {"document", "type", "source", "content", "truncated", "comments"}
    assert ["resolved" in c for c in result["comments"]] == [True, False, True, False]


def run_read_docx(*arguments):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "read_docx.py"), *(str(argument) for argument in arguments)],
        capture_output=True,
    )


def test_command_line_lists_unresolved_threads(tmp_path):
    completed = run_read_docx(threads_docx(tmp_path), "--comments", "--unresolved")

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.decode("utf-8"))
    assert result["summary"] == "2 open of 4 threads"
    assert [c["id"] for c in result["comments"]] == ["1", "6"]
    assert "content" not in result


def test_unresolved_without_comments_is_an_error_naming_the_usage(tmp_path):
    completed = run_read_docx(threads_docx(tmp_path), "--unresolved")

    assert completed.returncode == 2
    assert completed.stdout == b""
    assert b"--comments --unresolved" in completed.stderr


def test_comments_with_outline_only_or_show_changes_is_an_error(tmp_path):
    path = threads_docx(tmp_path)

    for flag in ("--outline-only", "--show-changes"):
        completed = run_read_docx(path, "--comments", flag)
        assert completed.returncode == 2
        assert b"--comments cannot be combined" in completed.stderr


def test_normalize_keeps_the_threads_the_counts_and_the_note(tmp_path, monkeypatch, capsys):
    import normalize_output

    source = tmp_path / "reader.json"
    payload = read_docx.comments(threads_docx(tmp_path, extended=False), None, None, None, unresolved_only=True)
    source.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["normalize_output.py", str(source)])
    assert normalize_output.main() == 0
    result = json.loads(capsys.readouterr().out)

    assert [(block["kind"], block["source"]["part"]) for block in result["blocks"]] == [("structure", "comments")]
    assert result["blocks"][0]["data"]["summary"] == "7 open of 7 threads"
    assert len(result["blocks"][0]["data"]["comments"]) == 7
    assert result["warnings"] == [payload["note"]]
