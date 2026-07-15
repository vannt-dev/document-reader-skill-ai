import cache_common as cc


def test_doc_id_for_slugifies_relative_path():
    assert cc.doc_id_for("api.xlsx") == "api-xlsx"
    assert cc.doc_id_for("sub/Business Rules.md") == "sub-business-rules-md"
    assert cc.doc_id_for("") == "doc"


def test_column_letter():
    assert cc.column_letter(1) == "A"
    assert cc.column_letter(26) == "Z"
    assert cc.column_letter(27) == "AA"


def test_excel_block_ranges_chunks_by_window():
    assert cc.excel_block_ranges(3, 500) == [(1, 3)]
    assert cc.excel_block_ranges(1200, 500) == [(1, 500), (501, 1000), (1001, 1200)]
    assert cc.excel_block_ranges(0, 500) == []


def test_slugify():
    assert cc.slugify("Authentication & Tokens") == "authentication-tokens"
    assert cc.slugify("!!!") == "section"


def test_markdown_sections_partition_without_overlap():
    lines = [
        "# Overview",      # 1
        "Intro.",          # 2
        "# Auth",          # 3
        "Log in.",         # 4
        "## Tokens",       # 5
        "Use JWT.",        # 6
    ]
    sections = cc.markdown_sections(lines)
    assert [(s["title"], s["start"], s["end"]) for s in sections] == [
        ("Overview", 1, 2),
        ("Auth", 3, 4),
        ("Tokens", 5, 6),
    ]


def test_markdown_sections_captures_preamble():
    lines = ["Preamble line.", "# First", "Body."]
    sections = cc.markdown_sections(lines)
    assert sections[0]["title"] is None
    assert (sections[0]["start"], sections[0]["end"]) == (1, 1)


def test_markdown_headings_ignore_fenced_code():
    lines = ["# Real", "```", "# Fake in fence", "```"]
    titles = [h["title"] for h in cc.markdown_headings(lines)]
    assert titles == ["Real"]
