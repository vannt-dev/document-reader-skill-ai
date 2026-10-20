import json
import subprocess
import sys
from pathlib import Path

import pytest

import build_cache
import cache_changes
import query_cache

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

SPEC_V1 = """# Checkout
Rules for checkout.

## Limits
- REQ-1 A cart holds at most 50 items.
- REQ-2 Guests may check out.
  Guests give an email address.

## Fees
| ID | Fee |
|----|-----|
| REQ-3 | 2% for cards |
| REQ-4 | 1 EUR for transfers |

## Contact
Write to support.
"""

# A paragraph is inserted at the top (every line number moves), REQ-1 changes,
# REQ-2 is removed, REQ-5 is added, a table row changes, Contact is untouched.
SPEC_V2 = """# Checkout
Rules for checkout.

This page replaces the old checkout notes.

## Limits
- REQ-1 A cart holds at most 100 items.
- REQ-5 A cart expires after 30 days.

## Fees
| ID | Fee |
|----|-----|
| REQ-3 | 2% for cards |
| REQ-4 | 2 EUR for transfers |

## Contact
Write to support.
"""


def markdown_blocks(text, tmp_path):
    path = tmp_path / "spec.md"
    path.write_bytes(text.encode("utf-8"))
    return build_cache.extract_markdown(path)


def table_block(rows, sheet="API", headers=("ID", "Requirement", "Status")):
    return {
        "block_id": f"{sheet}!A1:C{len(rows) + 1}",
        "ref": {"sheet": sheet, "range": f"A1:C{len(rows) + 1}"},
        "label": sheet,
        "content": {
            "headers": list(headers),
            "rows": [{"row": number, "cells": cells} for number, cells in enumerate(rows, 2)],
        },
    }


# --- units -------------------------------------------------------------------


def test_units_key_sections_by_heading_path_and_requirements_by_id(tmp_path):
    units = cache_changes.units(markdown_blocks(SPEC_V1, tmp_path))

    sections = [key for key, unit in units.items() if unit["kind"] == "section"]
    assert sections == ["Checkout", "Checkout > Limits", "Checkout > Fees", "Checkout > Contact"]

    requirements = {key: unit for key, unit in units.items() if unit["kind"] == "requirement"}
    assert list(requirements) == ["REQ-1", "REQ-2", "REQ-3", "REQ-4"]
    # A list item runs on to its continuation line; a table row is one line.
    assert requirements["REQ-2"]["text"] == "- REQ-2 Guests may check out.\n  Guests give an email address."
    assert requirements["REQ-3"]["text"] == "| REQ-3 | 2% for cards |"
    assert requirements["REQ-1"]["block_id"].startswith("limits@L")
    assert requirements["REQ-1"]["block_line"] == 2


def test_units_find_ids_in_headings_numbered_lists_and_custom_patterns():
    blocks = [{
        "block_id": "b", "ref": {"heading": "REQ-7 Login", "level": 2}, "label": "REQ-7 Login",
        "content": {"text": "## REQ-7 Login\n1. FR-7.1 Password\n2. **US-12** Remember me\nSee REQ-1 for limits."},
    }]
    units = cache_changes.units(blocks)
    assert [key for key, unit in units.items() if unit["kind"] == "requirement"] == ["REQ-7", "FR-7.1", "US-12"]
    # A mention inside a sentence does not define the requirement.
    assert "REQ-1" not in units

    custom = cache_changes.units(blocks, r"req\.\d+")
    assert [unit["kind"] for unit in custom.values()] == ["section"]


def test_units_number_repeated_keys():
    blocks = [
        {"block_id": f"b{n}", "ref": {"heading": "Notes", "level": 1}, "label": "Notes", "content": {"text": "x"}}
        for n in range(3)
    ]
    assert list(cache_changes.units(blocks)) == ["Notes", "Notes#2", "Notes#3"]


def test_units_key_rows_by_requirement_id_then_first_cell():
    blocks = [table_block([["REQ-1", "Login", "done"], ["Note", "no id here", ""], [None, "", "x"]])]
    units = cache_changes.units(blocks)

    assert list(units) == ["API > (header)", "API > REQ-1", "API > Note", "API > row 4"]
    assert units["API > REQ-1"]["requirement_id"] == "REQ-1"
    assert units["API > REQ-1"]["ref"] == {"sheet": "API", "row": 2}
    assert units["API > Note"]["label"] == "API row 3: Note"


# --- compare -----------------------------------------------------------------


def test_compare_reports_only_what_changed_when_lines_move(tmp_path):
    report = cache_changes.compare(markdown_blocks(SPEC_V1, tmp_path), markdown_blocks(SPEC_V2, tmp_path))

    keys = {name: [entry["key"] for entry in report[name]] for name in ("added", "changed", "removed")}
    assert keys == {
        "added": ["REQ-5"],
        "changed": ["Checkout", "Checkout > Limits", "REQ-1", "Checkout > Fees", "REQ-4"],
        "removed": ["REQ-2"],
    }
    # Contact and REQ-3 moved down three lines but did not change.
    assert report["summary"] == {"added": 1, "changed": 5, "removed": 1, "unchanged": 2}

    changed = {entry["key"]: entry for entry in report["changed"]}
    assert changed["REQ-1"]["diff"] == [
        "-- REQ-1 A cart holds at most 50 items.",
        "+- REQ-1 A cart holds at most 100 items.",
    ]
    assert changed["REQ-1"]["block_id"].startswith("limits@L6-")  # points at the new version
    added = report["added"][0]
    assert added["after"]["text"] == "- REQ-5 A cart expires after 30 days."
    removed = report["removed"][0]
    assert removed["before"]["text"].startswith("- REQ-2 Guests may check out.")
    assert removed["ref"]["lines"][0] == 4  # where it was in the old version


def test_compare_rows_by_id_survives_inserted_rows():
    old = [table_block([["REQ-1", "Login", "pending"], ["REQ-2", "Logout", "pending"]])]
    new = [table_block([
        ["REQ-0", "Register", "pending"],
        ["REQ-1", "Login", "pending"],
        ["REQ-2", "Logout", "done"],
    ])]

    report = cache_changes.compare(old, new)
    assert [entry["key"] for entry in report["added"]] == ["API > REQ-0"]
    assert report["added"][0]["after"] == {"cells": ["REQ-0", "Register", "pending"]}
    assert [entry["key"] for entry in report["changed"]] == ["API > REQ-2"]
    assert report["changed"][0]["before"] == {"cells": ["REQ-2", "Logout", "pending"]}
    assert report["changed"][0]["after"] == {"cells": ["REQ-2", "Logout", "done"]}
    assert report["changed"][0]["ref"] == {"sheet": "API", "row": 4}
    assert report["removed"] == []
    assert report["summary"]["unchanged"] == 2  # the header and REQ-1


def test_compare_reports_a_changed_header_once_per_sheet():
    old = [table_block([["REQ-1", "a", "b"]]), table_block([["REQ-9", "c", "d"]], sheet="Other")]
    new = [
        table_block([["REQ-1", "a", "b"]], headers=("ID", "Text", "State")),
        table_block([["REQ-9", "c", "d"]], sheet="Other"),
    ]
    report = cache_changes.compare(old, new)
    assert [entry["key"] for entry in report["changed"]] == ["API > (header)"]


def test_compare_caps_the_number_of_entries(monkeypatch):
    monkeypatch.setattr(cache_changes, "MAX_ENTRIES", 3)
    old = [table_block([[f"REQ-{n}", "x", ""] for n in range(5)])]
    new = [table_block([[f"REQ-{n}", "y", ""] for n in range(5)])]

    report = cache_changes.compare(old, new)
    assert report["summary"]["changed"] == 5
    assert len(report["changed"]) == 3
    assert report["truncated"] is True


def test_compare_bounds_long_diffs(monkeypatch):
    monkeypatch.setattr(cache_changes, "MAX_DIFF_LINES", 4)
    old = [{"block_id": "p", "ref": {"page": 1}, "label": "Page 1", "content": {"text": "\n".join("abcdefgh")}}]
    new = [{"block_id": "p", "ref": {"page": 1}, "label": "Page 1", "content": {"text": "\n".join("ABCDEFGH")}}]

    entry = cache_changes.compare(old, new)["changed"][0]
    assert len(entry["diff"]) == 4 and entry["diff_truncated"] is True


# --- build_cache and query_cache ---------------------------------------------


def write_spec(tmp_path, text):
    path = tmp_path / "spec.md"
    path.write_bytes(text.encode("utf-8"))
    return path


def test_build_records_changes_only_when_the_hash_changes(tmp_path, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    spec = write_spec(tmp_path, SPEC_V1)
    index = build_cache.build(manifest_for([spec], cache_dir), cache_dir, window=500)
    assert "changes" not in index["documents"][0]
    first = query_cache.changes(cache_dir, doc="spec-md")
    assert first["documents"] == [{
        "doc_id": "spec-md", "path": "spec.md", "sha256": index["documents"][0]["sha256"],
        "status": "no_previous_version",
    }]

    old_sha = index["documents"][0]["sha256"]
    write_spec(tmp_path, SPEC_V2)
    index = build_cache.build(manifest_for([spec], cache_dir), cache_dir, window=500)
    assert index["documents"][0]["changes"] == {
        "previous_sha256": old_sha, "added": 1, "changed": 5, "removed": 1, "unchanged": 2,
    }
    cached = json.loads((cache_dir / "cache" / "spec-md.json").read_text(encoding="utf-8"))
    assert cached["changes"]["previous_sha256"] == old_sha

    # Rebuilding the same version, even with --force, keeps the report.
    index = build_cache.build(manifest_for([spec], cache_dir), cache_dir, window=500, force=True)
    assert index["documents"][0]["changes"]["changed"] == 5

    report = query_cache.changes(cache_dir, doc="spec-md")
    document = report["documents"][0]
    assert document["status"] == "changed"
    assert document["previous_sha256"] == old_sha
    assert [entry["key"] for entry in document["added"]] == ["REQ-5"]
    assert report["truncated"] is False and report["warnings"] == []


def test_a_cache_written_before_change_reports_still_works(tmp_path, manifest_for):
    """A 1.0.0 cache file has no `changes`: it reads as no previous version,
    and is the version compared against once the document changes."""
    cache_dir = tmp_path / ".document-reader"
    spec = write_spec(tmp_path, SPEC_V1)
    build_cache.build(manifest_for([spec], cache_dir), cache_dir, window=500)
    assert query_cache.changes(cache_dir)["documents"] == []  # nothing to report, nothing listed

    write_spec(tmp_path, SPEC_V2)
    index = build_cache.build(manifest_for([spec], cache_dir), cache_dir, window=500)
    assert index["documents"][0]["changes"]["added"] == 1


def test_no_report_against_a_version_that_failed_to_read(tmp_path, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    spec = write_spec(tmp_path, SPEC_V1)
    manifest = manifest_for([spec], cache_dir)
    build_cache.build(manifest, cache_dir, window=500)
    cache_file = cache_dir / "cache" / "spec-md.json"
    broken = json.loads(cache_file.read_text(encoding="utf-8"))
    broken.update({"sha256": "old", "blocks": [], "error": "could not read"})
    cache_file.write_text(json.dumps(broken), encoding="utf-8")

    index = build_cache.build(manifest, cache_dir, window=500)
    assert "changes" not in index["documents"][0]


def test_changes_withholds_a_stale_document_and_bounds_results(tmp_path, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    spec = write_spec(tmp_path, SPEC_V1)
    build_cache.build(manifest_for([spec], cache_dir), cache_dir, window=500)
    write_spec(tmp_path, SPEC_V2)
    build_cache.build(manifest_for([spec], cache_dir), cache_dir, window=500)

    limited = query_cache.changes(cache_dir, max_results=2)
    document = limited["documents"][0]
    assert len(document["changed"]) == 2 and document["added"] == [] and document["removed"] == []
    assert document["summary"]["changed"] == 5
    assert limited["truncated"] is True

    # The file changes again but the cache is not rebuilt yet.
    write_spec(tmp_path, SPEC_V1)
    manifest_for([spec], cache_dir)
    stale = query_cache.changes(cache_dir, doc="spec-md")
    assert stale["documents"][0]["status"] == "stale"
    assert "changed" not in stale["documents"][0]
    assert any("stale" in warning for warning in stale["warnings"])

    assert query_cache.changes(cache_dir, doc="nope")["warnings"] == ["No document with doc_id 'nope' in index.json."]


def test_command_line_reports_changed_documents(tmp_path, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    spec = write_spec(tmp_path, SPEC_V1)
    manifest = manifest_for([spec], cache_dir)

    def run(script, *args):
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / script), *args],
            capture_output=True, text=True, encoding="utf-8",
        )
        return completed.returncode, completed.stdout, completed.stderr

    build_args = ("--manifest", str(manifest), "--cache-dir", str(cache_dir))
    code, out, _ = run("build_cache.py", *build_args)
    assert code == 0 and json.loads(out)["changed"] == []

    write_spec(tmp_path, SPEC_V2)
    manifest = manifest_for([spec], cache_dir)
    code, out, _ = run("build_cache.py", *build_args)
    assert json.loads(out)["changed"] == ["spec-md"]
    code, out, _ = run("build_cache.py", *build_args)  # nothing new since the last build
    assert json.loads(out)["changed"] == []

    code, out, _ = run("query_cache.py", "--changes", "--doc", "spec-md", "--cache-dir", str(cache_dir))
    assert code == 0
    assert json.loads(out)["documents"][0]["summary"]["removed"] == 1

    code, _, err = run("query_cache.py", "REQ", "--changes", "--cache-dir", str(cache_dir))
    assert code == 2 and "--changes takes only" in err
    code, _, err = run("build_cache.py", *build_args, "--id-pattern", "(")
    assert code == 2


def test_cache_file_schema_allows_the_change_report():
    schema = json.loads((SCRIPTS.parent / "schemas" / "document-cache-file.schema.json").read_text(encoding="utf-8"))
    assert "changes" in schema["properties"]
    index_schema = json.loads((SCRIPTS.parent / "schemas" / "document-cache.schema.json").read_text(encoding="utf-8"))
    assert "changes" in index_schema["properties"]["documents"]["items"]["properties"]


@pytest.mark.parametrize("line, expected", [
    ("REQ-12 Login", "REQ-12"),
    ("- [ ] FR-3.1 Export", "FR-3.1"),
    ("| BR_7 | rule |", "BR_7"),
    ("REQ-AUTH-3: lockout", "REQ-AUTH-3"),
    ("Requirement REQ-1", None),
    ("req-1 lower case", None),
])
def test_requirement_id_definitions(line, expected):
    import re

    assert cache_changes._defined_id(line, re.compile(cache_changes.DEFAULT_ID_PATTERN)) == expected
