import json
import zipfile

import pytest

import build_cache
import doc_text
import index_documents
import query_cache
import read_docx
import read_pdf
from conftest import docx_paragraph, write_docx


# --- .docx -----------------------------------------------------------------


def test_docx_items_keep_order_kinds_and_levels(sample_docx):
    items = doc_text.docx_items(sample_docx)

    assert [(item["index"], item["kind"], item["level"]) for item in items] == [
        (1, "paragraph", None),
        (2, "heading", 1),
        (3, "paragraph", None),
        (4, "heading", 1),
        (5, "paragraph", None),
        (6, "heading", 2),
        (7, "paragraph", None),
        (8, "table_row", None),
        (9, "table_row", None),
    ]
    assert items[8]["text"] == "R-1 | Lock after 5 attempts"


def test_docx_heading_comes_from_the_style_name_not_the_localised_id(tmp_path):
    styles = '<w:style w:type="paragraph" w:styleId="berschrift3"><w:name w:val="heading 3"/></w:style>'
    path = write_docx(tmp_path / "de.docx", docx_paragraph("Anmeldung", "berschrift3"), styles)

    assert doc_text.docx_outline(doc_text.docx_items(path)) == [{"level": 3, "title": "Anmeldung", "paragraph": 1}]


def test_docx_heading_falls_back_to_the_style_id_without_styles_part(tmp_path):
    path = write_docx(tmp_path / "plain.docx", docx_paragraph("Scope", "Heading2") + docx_paragraph("Body"))

    items = doc_text.docx_items(path)
    assert (items[0]["kind"], items[0]["level"]) == ("heading", 2)
    assert items[1]["kind"] == "paragraph"


def test_docx_reads_tabs_breaks_and_content_controls(tmp_path):
    body = (
        "<w:sdt><w:sdtContent>"
        "<w:p><w:r><w:t>a</w:t><w:tab/><w:t>b</w:t><w:br/><w:t>c</w:t></w:r></w:p>"
        "</w:sdtContent></w:sdt>"
    )
    path = write_docx(tmp_path / "sdt.docx", body)

    assert [item["text"] for item in doc_text.docx_items(path)] == ["a\tb\nc"]


def test_docx_reads_a_text_box_once(tmp_path):
    mc = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    body = (
        f'<w:p><w:r><mc:AlternateContent xmlns:mc="{mc}">'
        "<mc:Choice><w:p><w:r><w:t>Datum plane</w:t></w:r></w:p></mc:Choice>"
        "<mc:Fallback><w:p><w:r><w:t>Datum plane</w:t></w:r></w:p></mc:Fallback>"
        "</mc:AlternateContent></w:r></w:p>"
    )
    path = write_docx(tmp_path / "textbox.docx", body)

    assert [item["text"] for item in doc_text.docx_items(path)] == ["Datum plane"]


def test_docx_reads_strict_open_xml(tmp_path):
    strict = "http://purl.oclc.org/ooxml/wordprocessingml/main"
    path = tmp_path / "strict.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{strict}"><w:body>'
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Scope</w:t></w:r></w:p>'
            "</w:body></w:document>",
        )

    assert doc_text.docx_outline(doc_text.docx_items(path)) == [{"level": 1, "title": "Scope", "paragraph": 1}]


def test_docx_rejects_legacy_doc_and_dtd(tmp_path):
    legacy = tmp_path / "old.docx"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0 not a zip")
    with pytest.raises(ValueError, match="legacy .doc"):
        doc_text.docx_items(legacy)

    hostile = tmp_path / "dtd.docx"
    with zipfile.ZipFile(hostile, "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY a "b">]><x/>')
    with pytest.raises(ValueError, match="DTD"):
        doc_text.docx_items(hostile)


def test_read_docx_outline_and_heading_section(sample_docx):
    outline = read_docx.outline(sample_docx)
    assert outline["paragraph_count"] == 9
    assert outline["table_rows"] == 2
    assert [(h["level"], h["title"], h["paragraph"]) for h in outline["outline"]] == [
        (1, "Overview", 2), (1, "Authentication", 4), (2, "Tokens", 6),
    ]

    # A level-1 section includes its level-2 children, up to the end of the document here.
    section = read_docx.read(sample_docx, "authentication", None, None, 12000)
    assert section["source"] == {
        "heading": {"title": "Authentication", "level": 1}, "start_paragraph": 4, "end_paragraph": 9,
    }
    assert section["content"].splitlines()[:3] == ["# Authentication", "Users must log in.", "## Tokens"]

    overview = read_docx.read(sample_docx, "Overview", None, None, 12000)
    assert overview["content"] == "# Overview\nIntro text."


def test_read_docx_range_truncation_and_unknown_heading(sample_docx):
    ranged = read_docx.read(sample_docx, None, 5, 5, 12000)
    assert ranged["content"] == "Users must log in."

    short = read_docx.read(sample_docx, None, None, None, 10)
    assert short["truncated"] is True and len(short["content"]) == 10

    with pytest.raises(ValueError, match="Heading not found"):
        read_docx.read(sample_docx, "Missing", None, None, 12000)


# --- .pdf ------------------------------------------------------------------


def test_read_pdf_outline_reports_pages_without_text(sample_pdf):
    outline = read_pdf.outline(sample_pdf)

    assert outline["page_count"] == 3
    assert outline["pages_without_text"] == [2]
    assert outline["pages"][0]["chars"] > 0


def test_read_pdf_marks_pages_and_honours_a_range(sample_pdf):
    everything = read_pdf.read(sample_pdf, None, 12000)
    assert everything["source"] == {"start_page": 1, "end_page": 3}
    assert "--- page 1 ---\nSecurity policy\nPasswords expire after 90 days." in everything["content"]
    assert "--- page 3 ---\nAudit" in everything["content"]
    assert everything["pages_without_text"] == [2]

    last = read_pdf.read(sample_pdf, "3", 12000)
    assert last["source"] == {"start_page": 3, "end_page": 3}
    assert "Security policy" not in last["content"]


def test_parse_pages_validates_the_range():
    assert read_pdf.parse_pages(None, 10) == (1, 10)
    assert read_pdf.parse_pages("3-5", 10) == (3, 5)
    assert read_pdf.parse_pages("8-20", 10) == (8, 10)
    for bad in ("0", "5-3", "x", "11"):
        with pytest.raises(ValueError):
            read_pdf.parse_pages(bad, 10)


# --- normalize -------------------------------------------------------------


def _normalize(payload, tmp_path, monkeypatch, capsys):
    import normalize_output

    source = tmp_path / "reader.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["normalize_output.py", str(source)])
    assert normalize_output.main() == 0
    return json.loads(capsys.readouterr().out)


def test_normalize_accepts_pdf_and_docx_reader_output(sample_pdf, sample_docx, tmp_path, monkeypatch, capsys):
    text = _normalize(read_pdf.read(sample_pdf, None, 12000), tmp_path, monkeypatch, capsys)
    assert text["documents"][0]["type"] == "pdf"
    assert text["blocks"][0]["kind"] == "text"
    assert text["warnings"] == ["No text could be extracted from page(s) 2; they may be scanned images."]

    structure = _normalize(read_pdf.outline(sample_pdf), tmp_path, monkeypatch, capsys)
    assert structure["blocks"][0]["kind"] == "structure"
    assert structure["blocks"][0]["data"]["page_count"] == 3

    section = _normalize(read_docx.read(sample_docx, "Tokens", None, None, 12000), tmp_path, monkeypatch, capsys)
    assert section["blocks"][0]["data"].startswith("## Tokens")

    outline = _normalize(read_docx.outline(sample_docx), tmp_path, monkeypatch, capsys)
    assert [heading["title"] for heading in outline["blocks"][0]["data"]] == ["Overview", "Authentication", "Tokens"]


# --- index, cache, query ---------------------------------------------------


def test_index_metadata_for_docx_and_pdf(sample_docx, sample_pdf):
    docx = index_documents.docx_metadata(sample_docx, 2)
    assert docx["paragraph_count"] == 9
    assert [h["title"] for h in docx["headings"]] == ["Overview", "Authentication"]
    assert docx["headings_truncated"] is True

    pdf = index_documents.pdf_metadata(sample_pdf, 200)
    assert pdf == {"page_count": 3, "bookmarks": [], "bookmarks_truncated": False}


def test_build_cache_extracts_docx_sections(tmp_path, sample_docx, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    index = build_cache.build(manifest_for([sample_docx], cache_dir), cache_dir, window=500)

    document = index["documents"][0]
    assert document["type"] == "docx"
    assert [block["label"] for block in document["blocks"]] == ["(preamble)", "Overview", "Authentication", "Tokens"]

    cached = json.loads((cache_dir / "cache" / "spec-docx.json").read_text(encoding="utf-8"))
    tokens = next(block for block in cached["blocks"] if block["label"] == "Tokens")
    assert tokens["block_id"] == "tokens@P6-9"
    assert tokens["ref"] == {"heading": "Tokens", "level": 2, "paragraphs": [6, 9]}
    assert tokens["content"]["text"].endswith("R-1 | Lock after 5 attempts")


def test_build_cache_extracts_pdf_pages_and_query_finds_them(tmp_path, sample_pdf, manifest_for):
    cache_dir = tmp_path / ".document-reader"
    index = build_cache.build(manifest_for([sample_pdf], cache_dir), cache_dir, window=500)

    document = index["documents"][0]
    assert document["type"] == "pdf"
    # Page 2 has no text layer, so it produces no block.
    assert [block["block_id"] for block in document["blocks"]] == ["page-1", "page-3"]

    result = query_cache.query(cache_dir, keyword="recorded")
    assert [(r["block_id"], r["ref"]) for r in result["results"]] == [("page-3", {"page": 3})]


def test_build_cache_records_an_unreadable_document_without_aborting(tmp_path, sample_md, manifest_for):
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip")
    cache_dir = tmp_path / ".document-reader"

    index = build_cache.build(manifest_for([broken, sample_md], cache_dir), cache_dir, window=500)

    by_path = {document["path"]: document for document in index["documents"]}
    assert "legacy .doc" in by_path["broken.docx"]["error"]
    assert by_path["broken.docx"]["blocks"] == []
    assert len(by_path["business.md"]["blocks"]) == 3
