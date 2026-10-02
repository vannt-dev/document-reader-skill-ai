import pytest


@pytest.fixture
def sample_md(tmp_path):
    path = tmp_path / "business.md"
    path.write_text(
        "# Overview\nIntro text.\n\n# Authentication\nUsers must log in.\n\n"
        "## Tokens\nUse JWT.\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def sample_xlsx(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "api.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "API"
    sheet.append(["ID", "Requirement", "Status"])
    sheet.append(["REQ-1", "Login endpoint", "pending"])
    sheet.append(["REQ-2", "Logout endpoint", "pending"])
    workbook.save(path)
    return path


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def write_docx(path, body_xml, styles_xml=None):
    """Write a minimal .docx: only the parts the reader looks at."""
    import zipfile

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W_NS}"><w:body>{body_xml}</w:body></w:document>',
        )
        if styles_xml is not None:
            archive.writestr(
                "word/styles.xml",
                f'<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="{W_NS}">{styles_xml}</w:styles>',
            )
    return path


def docx_paragraph(text, style=None):
    properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{properties}<w:r><w:t>{text}</w:t></w:r></w:p>"


@pytest.fixture
def sample_docx(tmp_path):
    # The style ids are localised on purpose: only the style *name* says "heading".
    styles = (
        '<w:style w:type="paragraph" w:styleId="Tiu1"><w:name w:val="heading 1"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Tiu2"><w:name w:val="heading 2"/></w:style>'
    )
    table = (
        "<w:tbl>"
        "<w:tr><w:tc><w:p><w:r><w:t>ID</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Rule</w:t></w:r></w:p></w:tc></w:tr>"
        "<w:tr><w:tc><w:p><w:r><w:t>R-1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Lock after 5 attempts</w:t></w:r></w:p></w:tc></w:tr>"
        "</w:tbl>"
    )
    body = "".join([
        docx_paragraph("Document preamble."),
        docx_paragraph("Overview", "Tiu1"),
        docx_paragraph("Intro text."),
        "<w:p/>",
        docx_paragraph("Authentication", "Tiu1"),
        docx_paragraph("Users must log in."),
        docx_paragraph("Tokens", "Tiu2"),
        docx_paragraph("Use JWT."),
        table,
    ])
    return write_docx(tmp_path / "spec.docx", body, styles)


def write_pdf(path, pages):
    """Write a minimal text PDF; `pages` is a list of lists of lines."""
    def escape(text):
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    objects = {3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    kids = []
    next_id = 4
    for lines in pages:
        stream = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(f"({escape(line)}) Tj T*" for line in lines) + " ET"
        page_id, content_id = next_id, next_id + 1
        next_id += 2
        kids.append(page_id)
        objects[page_id] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        )
        objects[content_id] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
    objects[1] = "<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{' '.join(f'{kid} 0 R' for kid in kids)}] /Count {len(kids)} >>"

    data = b"%PDF-1.4\n"
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(data)
        data += f"{number} 0 obj\n{objects[number]}\nendobj\n".encode("latin-1")
    xref = len(data)
    data += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
    for number in sorted(objects):
        data += f"{offsets[number]:010d} 00000 n \n".encode("latin-1")
    data += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1")
    path.write_bytes(data)
    return path


@pytest.fixture
def sample_pdf(tmp_path):
    pytest.importorskip("pypdf")
    return write_pdf(tmp_path / "policy.pdf", [
        ["Security policy", "Passwords expire after 90 days."],
        [],
        ["Audit", "Every login is recorded."],
    ])


A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def pptx_shape(text, placeholder=None):
    """One text shape; `text` may hold several paragraphs separated by newlines."""
    ph = f'<p:nvPr><p:ph type="{placeholder}"/></p:nvPr>' if placeholder else "<p:nvPr/>"
    paragraphs = "".join(f"<a:p><a:r><a:t>{line}</a:t></a:r></a:p>" for line in text.split("\n"))
    return f"<p:sp><p:nvSpPr>{ph}</p:nvSpPr><p:txBody>{paragraphs}</p:txBody></p:sp>"


def pptx_table(rows):
    body = "".join(
        "<a:tr>" + "".join(
            f"<a:tc><a:txBody><a:p><a:r><a:t>{cell}</a:t></a:r></a:p></a:txBody></a:tc>" for cell in row
        ) + "</a:tr>"
        for row in rows
    )
    return f"<p:graphicFrame><a:graphic><a:graphicData><a:tbl>{body}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>"


def write_pptx(path, slides, p_ns=P_NS, a_ns=A_NS, r_ns=R_NS):
    """Write a minimal .pptx. `slides` is a list of (shapes_xml, notes_or_None).

    Slides are stored under shuffled part names so the reader has to follow the
    presentation's own order rather than the file names.
    """
    import zipfile

    def rels(items):
        body = "".join(
            f'<Relationship Id="{rid}" Type="{REL_TYPE}/{kind}" Target="{target}"/>'
            for rid, kind, target in items
        )
        return f'<Relationships xmlns="{REL_NS}">{body}</Relationships>'

    def sheet(tag, shapes):
        return (
            f'<p:{tag} xmlns:p="{p_ns}" xmlns:a="{a_ns}" xmlns:r="{r_ns}">'
            f"<p:cSld><p:spTree>{shapes}</p:spTree></p:cSld></p:{tag}>"
        )

    with zipfile.ZipFile(path, "w") as archive:
        part_numbers = list(range(len(slides), 0, -1))
        ids = "".join(f'<p:sldId id="{255 + i}" r:id="rId{i}"/>' for i in range(1, len(slides) + 1))
        archive.writestr(
            "ppt/presentation.xml",
            f'<p:presentation xmlns:p="{p_ns}" xmlns:r="{r_ns}"><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>',
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            rels([(f"rId{i}", "slide", f"slides/slide{part}.xml") for i, part in enumerate(part_numbers, 1)]),
        )
        for (shapes, notes), part in zip(slides, part_numbers):
            archive.writestr(f"ppt/slides/slide{part}.xml", sheet("sld", shapes))
            if notes is not None:
                archive.writestr(
                    f"ppt/slides/_rels/slide{part}.xml.rels",
                    rels([("rId1", "notesSlide", f"../notesSlides/notesSlide{part}.xml")]),
                )
                archive.writestr(
                    f"ppt/notesSlides/notesSlide{part}.xml",
                    sheet("notes", pptx_shape("7", "sldNum") + pptx_shape(notes, "body")),
                )
    return path


@pytest.fixture
def sample_pptx(tmp_path):
    return write_pptx(tmp_path / "kickoff.pptx", [
        (pptx_shape("Project kickoff", "ctrTitle") + pptx_shape("Q3 planning", "subTitle"), None),
        (
            pptx_shape("Authentication", "title")
            + pptx_shape("Users must log in.\nSessions expire after 30 minutes.")
            + pptx_table([["ID", "Rule"], ["R-1", "Lock after 5 attempts"]]),
            "Mention the audit finding.",
        ),
        (pptx_shape("No title on this slide, only a text box."), None),
    ])


@pytest.fixture
def sample_csv(tmp_path):
    path = tmp_path / "rules.csv"
    path.write_text(
        'ID;Requirement;Status\n'
        'REQ-1;"Login; with MFA";pending\n'
        '\n'
        'REQ-2;Logout endpoint;done\n'
        'REQ-3;"Password\nreset";pending\n',
        encoding="utf-8-sig",
    )
    return path


@pytest.fixture
def manifest_for(tmp_path):
    """Build a manifest.json referencing given files, return its path."""
    import json
    from common import DOCUMENT_TYPES
    from index_documents import digest

    def _make(paths, cache_dir):
        documents = []
        for path in paths:
            documents.append({
                "path": path.name,
                "type": DOCUMENT_TYPES[path.suffix.lower()],
                "sha256": digest(path),
            })
        manifest = {
            "schema_version": "1.0",
            "requirements_root": str(tmp_path),
            "documents": documents,
        }
        cache_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = cache_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    return _make
