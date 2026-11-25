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


def write_docx(path, body_xml, styles_xml=None, parts=None):
    """Write a minimal .docx: only the parts the reader looks at.

    `parts` maps further part names (word/comments.xml ...) to their XML.
    """
    import zipfile

    with zipfile.ZipFile(path, "w") as archive:
        for name, xml in (parts or {}).items():
            archive.writestr(name, xml)
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


def write_raw_pdf(path, streams):
    """Write a PDF whose pages are the given content streams."""
    objects = {3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    kids = []
    next_id = 4
    for stream in streams:
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


def text_at(x, y, text):
    return f"BT /F1 10 Tf {x} {y} Td ({text}) Tj ET"


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


# A trimmed Confluence "Export to HTML" page: breadcrumbs, the page title, the
# body with a nested list and a table, the attachments footer, and the scripts
# and styles that surround it.
CONFLUENCE_HTML = """<!DOCTYPE html>
<html>
<head>
<title>Payments : Checkout rules</title>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<style>body { font-family: Arial; }</style>
<script>var trackingId = "do-not-read";</script>
</head>
<body class="theme-default aui-theme-default">
<div id="page">
<div id="main-header">
<div id="breadcrumb-section"><ol id="breadcrumbs"><li><a href="index.html">Payments</a></li></ol></div>
<h1 id="title-heading" class="pagetitle">Checkout rules</h1>
</div>
<nav class="sidebar">Space navigation</nav>
<div id="content" class="view">
<div class="page-metadata">Created by Lan, last modified on 3 Oct 2026</div>
<div id="main-content" class="wiki-content group">
<p>Rules for the checkout page &amp; its API.</p>
<h2 id="rules-Limits">Limits</h2>
<ul>
<li>REQ-101 A cart holds at most 50 items.</li>
<li>Payment methods:
<ul><li>Card</li><li>Bank&nbsp;transfer</li></ul>
</li>
</ul>
<h2 id="rules-Fees">Fees</h2>
<ol><li>First step</li><li>Second step</li></ol>
<div class="table-wrap"><table class="confluenceTable"><tbody>
<tr><th class="confluenceTh">ID</th><th class="confluenceTh">Fee</th></tr>
<tr><td class="confluenceTd">REQ-102</td><td class="confluenceTd"><p>2% for cards</p></td></tr>
</tbody></table></div>
<pre>code line 1
    indented line 2</pre>
<p hidden>Hidden note</p>
</div>
</div>
<div id="footer" role="contentinfo"><section class="footer-body"><p>Document generated by Confluence</p></section></div>
</div>
<script>document.write("never");</script>
</body>
</html>
"""


@pytest.fixture
def sample_html(tmp_path):
    path = tmp_path / "checkout.html"
    path.write_bytes(CONFLUENCE_HTML.encode("utf-8"))
    return path


@pytest.fixture
def sample_txt(tmp_path):
    path = tmp_path / "notes.txt"
    # Written as bytes so the line endings are the same on every platform.
    path.write_bytes(
        b"Meeting notes, 3 Oct\r\n\r\n# Decisions\r\nREQ-201 Export to CSV.\r\n\r\n"
        b"# Open questions\r\nWho approves refunds?\r\n"
    )
    return path


def write_cfb(path, tree):
    """Write a minimal OLE compound file (version 3): `tree` maps names to bytes
    (a stream) or to a dict (a storage). Streams under 4096 bytes go in the mini
    stream, as the format requires; olefile reads the result."""
    import math
    import struct

    sector, mini_sector, cutoff = 512, 64, 4096
    free, end, fat_sector, no_stream = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF
    entries = []

    def add(name, node):
        entry, index = {"name": name}, len(entries)
        entries.append(entry)
        if isinstance(node, dict):
            entry["type"], entry["kids"] = 1, [add(key, value) for key, value in node.items()]
        else:
            entry["type"], entry["data"] = 2, bytes(node)
        return index

    add("Root Entry", tree)
    entries[0]["type"] = 5
    mini, mini_fat, big = bytearray(), [], []
    for entry in entries:
        if entry["type"] != 2:
            continue
        data = entry["data"]
        if not data:
            entry["start"] = end
        elif len(data) < cutoff:
            count = math.ceil(len(data) / mini_sector)
            entry["start"] = len(mini_fat)
            mini_fat += list(range(len(mini_fat) + 1, len(mini_fat) + count)) + [end]
            mini += data.ljust(count * mini_sector, b"\0")
        else:
            big.append(entry)

    dir_count = math.ceil(len(entries) * 128 / sector)
    mini_fat_count = math.ceil(len(mini_fat) * 4 / sector)
    mini_stream_count = math.ceil(len(mini) / sector)
    big_counts = [math.ceil(len(entry["data"]) / sector) for entry in big]
    others = dir_count + mini_fat_count + mini_stream_count + sum(big_counts)
    fat_count = 1
    while fat_count * (sector // 4) < others + fat_count:
        fat_count += 1
    fat = [fat_sector] * fat_count

    def chain(count):
        if not count:
            return end
        start = len(fat)
        fat.extend(list(range(start + 1, start + count)) + [end])
        return start

    dir_start = chain(dir_count)
    mini_fat_start = chain(mini_fat_count)
    entries[0]["start"] = chain(mini_stream_count)
    entries[0]["size"] = len(mini)
    for entry, count in zip(big, big_counts):
        entry["start"] = chain(count)
    fat += [free] * (fat_count * (sector // 4) - len(fat))

    def order(index):
        name = entries[index]["name"]
        return (len(name), name.upper())

    for entry in entries:
        entry.setdefault("left", no_stream)
        entry.setdefault("right", no_stream)
        entry["child"] = no_stream
    for entry in entries:
        kids = sorted(entry.get("kids", []), key=order)
        if kids:
            # A chain of right siblings in name order: a valid, if lopsided, tree.
            entry["child"] = kids[0]
            for here, after in zip(kids, kids[1:]):
                entries[here]["right"] = after

    directory = bytearray()
    for entry in entries:
        name = entry["name"].encode("utf-16-le")
        size = entry.get("size", len(entry.get("data", b"")))
        directory += struct.pack(
            "<64sHBBIII16sIQQIQ", name, len(name) + 2, entry["type"], 1,
            entry["left"], entry["right"], entry["child"], b"\0" * 16, 0, 0, 0,
            entry.get("start", end if entry["type"] == 2 else 0), size,
        )
    while len(directory) % sector:
        directory += struct.pack("<64sHBBIII16sIQQIQ", b"", 0, 0, 0, no_stream, no_stream, no_stream, b"\0" * 16, 0, 0, 0, 0, 0)

    difat = list(range(fat_count)) + [free] * (109 - fat_count)
    header = struct.pack(
        "<8s16sHHHHH6sIIIIIIIII109I", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"\0" * 16, 0x3E, 3, 0xFFFE, 9, 6,
        b"\0" * 6, 0, fat_count, dir_start, 0, cutoff,
        mini_fat_start if mini_fat_count else end, mini_fat_count, end, 0, *difat,
    )
    body = b"".join(struct.pack("<I", value) for value in fat)
    body += bytes(directory)
    body += b"".join(struct.pack("<I", value) for value in mini_fat).ljust(mini_fat_count * sector, b"\xff")
    body += bytes(mini).ljust(mini_stream_count * sector, b"\0")
    for entry, count in zip(big, big_counts):
        body += entry["data"].ljust(count * sector, b"\0")
    path.write_bytes(header + body)
    return path


def msg_properties(header_size, fixed):
    """A __properties_version1.0 stream: `fixed` maps (id, type) to 8 value bytes."""
    import struct

    data = b"\0" * header_size
    for (prop, kind), value in fixed.items():
        data += struct.pack("<II8s", (prop << 16) | kind, 6, value)
    return data


def msg_string(prop, text, codepage=None):
    """A string property stream: Unicode, or 8-bit in `codepage`."""
    if codepage:
        return {f"__substg1.0_{prop:04X}001E": text.encode(codepage)}
    return {f"__substg1.0_{prop:04X}001F": text.encode("utf-16-le")}


def msg_tree(strings, fixed=None, recipients=(), attachments=(), header_size=32, codepage=None, binaries=None):
    """The storages and streams of a .msg message.

    `recipients` are (type, name, address), type 1 To / 2 Cc; `attachments` are
    (name, mime type, bytes), or (name, None, a msg_tree(...)) for an attached Outlook item.
    """
    import struct

    tree = {}
    for prop, text in strings.items():
        tree.update(msg_string(prop, text, codepage))
    for prop, data in (binaries or {}).items():
        tree[f"__substg1.0_{prop:04X}0102"] = data
    fixed = dict(fixed or {})
    if codepage:
        fixed[(0x3FFD, 0x0003)] = struct.pack("<iI", int(codepage[2:]), 0)
    for number, (kind, name, address) in enumerate(recipients):
        storage = {"__properties_version1.0": msg_properties(8, {(0x0C15, 0x0003): struct.pack("<iI", kind, 0)})}
        storage.update(msg_string(0x3001, name, codepage))
        storage.update(msg_string(0x39FE, address, codepage))
        tree[f"__recip_version1.0_#{number:08X}"] = storage
    for number, (name, mime, data) in enumerate(attachments):
        storage = {"__properties_version1.0": msg_properties(8, {(0x3705, 0x0003): struct.pack("<iI", 5 if isinstance(data, dict) else 1, 0)})}
        storage.update(msg_string(0x3707, name, codepage))
        if mime:
            storage.update(msg_string(0x370E, mime, codepage))
        if isinstance(data, dict):
            storage["__substg1.0_3701000D"] = data
        else:
            storage["__substg1.0_37010102"] = data
        tree[f"__attach_version1.0_#{number:08X}"] = storage
    tree["__properties_version1.0"] = msg_properties(header_size, fixed)
    return tree
