"""Text extraction for PDF and Word (.docx) documents.

Read-only: nothing inside a document is executed, and no external link is followed.
PDF needs pypdf; .docx is read with the standard library only.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

W_URI = b"http://schemas.openxmlformats.org/wordprocessingml/2006/main"
# "Strict Open XML" documents use a different namespace for the same elements.
W_STRICT_URI = b"http://purl.oclc.org/ooxml/wordprocessingml/main"
W = "{" + W_URI.decode() + "}"
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PACKAGE_RELATIONSHIP = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
# Strict Open XML names the same elements under purl.oclc.org; map them back so
# one set of tag names reads both flavours.
STRICT_NAMESPACES = [
    (W_STRICT_URI, W_URI),
    (
        b"http://purl.oclc.org/ooxml/drawingml/main",
        b"http://schemas.openxmlformats.org/drawingml/2006/main",
    ),
    (
        b"http://purl.oclc.org/ooxml/presentationml/main",
        b"http://schemas.openxmlformats.org/presentationml/2006/main",
    ),
    (
        b"http://purl.oclc.org/ooxml/officeDocument/relationships",
        b"http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    ),
]
TITLE_PLACEHOLDERS = {"title", "ctrTitle"}
# A .docx part larger than this is refused rather than inflated into memory.
MAX_DOCX_PART_BYTES = 64 * 1024 * 1024
HEADING_NAME = re.compile(r"^heading\s*([1-9])$", re.IGNORECASE)


# --- PDF -------------------------------------------------------------------


def open_pdf(path: Path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF reading requires pypdf: python -m pip install pypdf") from exc
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception:  # noqa: BLE001 - any failure means we cannot read it
            unlocked = 0
        if not unlocked:
            raise ValueError("PDF is password-protected; remove the password and try again")
    return reader


def pdf_page_text(reader, number: int) -> str:
    """Text of a 1-based page; empty when the page has no text layer."""
    try:
        text = reader.pages[number - 1].extract_text() or ""
    except Exception:  # noqa: BLE001 - one broken page must not hide the others
        return ""
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def pdf_bookmarks(reader, limit: int) -> tuple[list[dict], bool]:
    """Flattened outline entries as (items, truncated)."""
    items: list[dict] = []
    truncated = False

    def walk(entries, level: int) -> None:
        nonlocal truncated
        for entry in entries:
            if isinstance(entry, list):
                walk(entry, level + 1)
                continue
            if len(items) >= limit:
                truncated = True
                return
            try:
                page = reader.get_destination_page_number(entry) + 1
            except Exception:  # noqa: BLE001 - a dangling bookmark still has a title
                page = None
            items.append({"level": level, "title": str(entry.title).strip(), "page": page})

    try:
        walk(reader.outline, 1)
    except Exception:  # noqa: BLE001 - a damaged outline is not worth failing the document
        return [], False
    return items, truncated


# --- DOCX ------------------------------------------------------------------


def _read_part(archive: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_DOCX_PART_BYTES:
        raise ValueError(f"{name} is too large to read safely ({info.file_size} bytes)")
    data = archive.read(info)
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError(f"{name} declares a DTD, which Office documents never need; refusing to parse it")
    for strict, transitional in STRICT_NAMESPACES:
        data = data.replace(strict, transitional)
    return data


def _style_levels(styles_xml: bytes | None) -> dict[str, int]:
    """Map paragraph style ids to heading levels.

    Word stores built-in style names in English ("heading 1") whatever the
    interface language, while the style id is localised, so the name is the
    reliable key.
    """
    levels: dict[str, int] = {}
    if not styles_xml:
        return levels
    for style in ElementTree.fromstring(styles_xml).iter(f"{W}style"):
        style_id = style.get(f"{W}styleId")
        if not style_id:
            continue
        name = style.find(f"{W}name")
        label = (name.get(f"{W}val") if name is not None else "") or ""
        if match := HEADING_NAME.match(label.strip()):
            levels[style_id] = int(match.group(1))
        elif label.strip().lower() == "title":
            levels[style_id] = 1
        else:
            outline = style.find(f"{W}pPr/{W}outlineLvl")
            if outline is not None and (outline.get(f"{W}val") or "").isdigit():
                levels[style_id] = min(int(outline.get(f"{W}val")) + 1, 9)
    return levels


def _paragraph_text(paragraph) -> str:
    parts: list[str] = []

    def collect(node) -> None:
        for child in node:
            # A text box is stored twice, as a drawing and as a legacy fallback; read it once.
            if child.tag == MC_FALLBACK:
                continue
            if child.tag == f"{W}t":
                parts.append(child.text or "")
            elif child.tag == f"{W}tab":
                parts.append("\t")
            elif child.tag in (f"{W}br", f"{W}cr"):
                parts.append("\n")
            else:
                collect(child)

    collect(paragraph)
    return "".join(parts).strip()


def _paragraph_level(paragraph, style_levels: dict[str, int]) -> int | None:
    properties = paragraph.find(f"{W}pPr")
    if properties is None:
        return None
    outline = properties.find(f"{W}outlineLvl")
    if outline is not None and (outline.get(f"{W}val") or "").isdigit():
        level = int(outline.get(f"{W}val")) + 1
        if level <= 9:
            return level
    style = properties.find(f"{W}pStyle")
    if style is None:
        return None
    style_id = style.get(f"{W}val") or ""
    if style_id in style_levels:
        return style_levels[style_id]
    if match := HEADING_NAME.match(style_id):
        return int(match.group(1))
    return None


def _walk(container, style_levels: dict[str, int]):
    for child in container:
        if child.tag == f"{W}p":
            text = _paragraph_text(child)
            if text:
                level = _paragraph_level(child, style_levels)
                yield {"kind": "heading" if level else "paragraph", "level": level, "text": text}
        elif child.tag == f"{W}tbl":
            for row in child.iter(f"{W}tr"):
                cells = []
                for cell in row.findall(f"{W}tc"):
                    texts = [_paragraph_text(p) for p in cell.iter(f"{W}p")]
                    cells.append(" ".join(text for text in texts if text).replace("\n", " "))
                if any(cells):
                    yield {"kind": "table_row", "level": None, "text": " | ".join(cells)}
        elif child.tag == f"{W}sdt":
            content = child.find(f"{W}sdtContent")
            if content is not None:
                yield from _walk(content, style_levels)


def docx_items(path: Path) -> list[dict]:
    """Non-empty paragraphs, headings and table rows in document order.

    Each item carries a 1-based `index`, which is the citation unit for .docx.
    """
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError(
            "Not a readable .docx file (legacy .doc and password-protected files are not supported)"
        ) from exc
    with archive:
        document = _read_part(archive, "word/document.xml")
        if document is None:
            raise ValueError("Not a Word document: word/document.xml is missing")
        style_levels = _style_levels(_read_part(archive, "word/styles.xml"))
    body = ElementTree.fromstring(document).find(f"{W}body")
    if body is None:
        return []
    items = list(_walk(body, style_levels))
    for index, item in enumerate(items, 1):
        item["index"] = index
    return items


def docx_outline(items: list[dict]) -> list[dict]:
    return [
        {"level": item["level"], "title": item["text"], "paragraph": item["index"]}
        for item in items
        if item["kind"] == "heading"
    ]


def docx_sections(items: list[dict]) -> list[dict]:
    """Split items at headings, with a leading untitled section for any preamble."""
    headings = [item for item in items if item["kind"] == "heading"]
    sections = []
    first = headings[0]["index"] if headings else len(items) + 1
    if first > 1:
        sections.append({"title": None, "level": 0, "start": 1, "end": first - 1})
    for position, heading in enumerate(headings):
        end = headings[position + 1]["index"] - 1 if position + 1 < len(headings) else len(items)
        sections.append({
            "title": heading["text"],
            "level": heading["level"],
            "start": heading["index"],
            "end": end,
        })
    return sections


def docx_render(items: list[dict]) -> str:
    """Plain text for a run of items; headings keep their level as Markdown hashes."""
    lines = []
    for item in items:
        if item["kind"] == "heading":
            lines.append(f"{'#' * item['level']} {item['text']}")
        else:
            lines.append(item["text"])
    return "\n".join(lines)


# --- PPTX ------------------------------------------------------------------


def _relationships(archive: zipfile.ZipFile, part: str) -> dict[str, dict]:
    """Relationships of a package part, keyed by id, with targets as part names."""
    folder, _, name = part.rpartition("/")
    data = _read_part(archive, f"{folder}/_rels/{name}.rels")
    if data is None:
        return {}
    relationships = {}
    for node in ElementTree.fromstring(data).iter(PACKAGE_RELATIONSHIP):
        if node.get("TargetMode") == "External":
            continue
        target = node.get("Target") or ""
        # Targets are relative to the part's folder unless they start with "/".
        segments = [] if target.startswith("/") else folder.split("/")
        for segment in target.split("/"):
            if segment == "..":
                if segments:
                    segments.pop()
            elif segment and segment != ".":
                segments.append(segment)
        relationships[node.get("Id") or ""] = {
            "type": (node.get("Type") or "").rsplit("/", 1)[-1],
            "target": "/".join(segments),
        }
    return relationships


def _drawing_paragraphs(container) -> list[str]:
    """Text of each `a:p` under `container`, one string per non-empty paragraph."""
    paragraphs = []
    for paragraph in container.iter(f"{A}p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == f"{A}t":
                parts.append(node.text or "")
            elif node.tag == f"{A}br":
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def _slide_content(root) -> tuple[str | None, list[str]]:
    """A slide's title and its other text, in the order shapes are stored."""
    title = None
    lines: list[str] = []
    tree = root.find(f"{P}cSld/{P}spTree")
    if tree is None:
        return None, lines

    def visit(container) -> None:
        nonlocal title
        for shape in container:
            if shape.tag == f"{P}sp":
                placeholder = shape.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
                paragraphs = _drawing_paragraphs(shape)
                is_title = placeholder is not None and placeholder.get("type") in TITLE_PLACEHOLDERS
                if is_title and title is None and paragraphs:
                    title = " ".join(paragraphs).replace("\n", " ")
                else:
                    lines.extend(paragraphs)
            elif shape.tag == f"{P}graphicFrame":
                for row in shape.iter(f"{A}tr"):
                    cells = [
                        " ".join(_drawing_paragraphs(cell)).replace("\n", " ")
                        for cell in row.findall(f"{A}tc")
                    ]
                    if any(cells):
                        lines.append(" | ".join(cells))
            elif shape.tag == f"{P}grpSp":
                visit(shape)

    visit(tree)
    return title, lines


def _notes_text(root) -> list[str]:
    """Speaker notes, without the slide-number and slide-image placeholders."""
    lines: list[str] = []
    for shape in root.iter(f"{P}sp"):
        placeholder = shape.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
        if placeholder is not None and placeholder.get("type") == "body":
            lines.extend(_drawing_paragraphs(shape))
    return lines


def pptx_slides(path: Path) -> list[dict]:
    """Slides in presentation order.

    Each slide carries a 1-based `slide` number (the citation unit for .pptx),
    its `title` (None when it has no title placeholder), the `lines` of its
    other text with table rows as `cell | cell`, and its speaker `notes`.
    """
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError(
            "Not a readable .pptx file (legacy .ppt and password-protected files are not supported)"
        ) from exc
    with archive:
        presentation = _read_part(archive, "ppt/presentation.xml")
        if presentation is None:
            raise ValueError("Not a PowerPoint presentation: ppt/presentation.xml is missing")
        relationships = _relationships(archive, "ppt/presentation.xml")
        slides = []
        entries = ElementTree.fromstring(presentation).iter(f"{P}sldId")
        for number, entry in enumerate(entries, 1):
            relationship = relationships.get(entry.get(f"{R}id") or "")
            data = _read_part(archive, relationship["target"]) if relationship else None
            if data is None:
                # Keep the numbering of the deck: a slide whose part is missing
                # is skipped, not renumbered away.
                continue
            title, lines = _slide_content(ElementTree.fromstring(data))
            notes: list[str] = []
            for linked in _relationships(archive, relationship["target"]).values():
                if linked["type"] == "notesSlide":
                    notes_data = _read_part(archive, linked["target"])
                    if notes_data is not None:
                        notes = _notes_text(ElementTree.fromstring(notes_data))
            slides.append({"slide": number, "title": title, "lines": lines, "notes": notes})
    return slides


def pptx_render(slide: dict, include_notes: bool = True) -> str:
    """Plain text of one slide: the title as a heading, then its text and notes."""
    lines = []
    if slide["title"]:
        lines.append(f"# {slide['title']}")
    lines.extend(slide["lines"])
    if include_notes and slide["notes"]:
        lines.append("Notes:")
        lines.extend(slide["notes"])
    return "\n".join(lines)
