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
W14 = "{http://schemas.microsoft.com/office/word/2010/wordml}"
W15 = "{http://schemas.microsoft.com/office/word/2012/wordml}"
REVISION_TYPES = {
    f"{W}ins": "inserted", f"{W}del": "deleted", f"{W}moveTo": "moved_to", f"{W}moveFrom": "moved_from",
}
# Gone once every change is accepted.
REMOVED_REVISIONS = {"deleted", "moved_from"}
CRITIC_MARKS = {
    "inserted": ("{++", "++}"), "moved_to": ("{++", "++}"),
    "deleted": ("{--", "--}"), "moved_from": ("{--", "--}"),
}


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


class _Ranges:
    """Comment ranges open while walking a document body; one can span paragraphs."""

    def __init__(self) -> None:
        self.open: dict[str, list[str]] = {}
        self.anchors: dict[str, str] = {}
        self.located: set[str] = set()

    def text(self, text: str) -> None:
        for parts in self.open.values():
            parts.append(text)

    def close(self, comment_id: str) -> None:
        if comment_id in self.open:
            self.anchors[comment_id] = "".join(self.open.pop(comment_id)).strip()


def _read_paragraph(paragraph, ranges: _Ranges) -> dict:
    """A paragraph's text with every tracked change accepted, and what it holds besides.

    `marked` is the text with the changes written in as CriticMarkup ({++inserted++},
    {--deleted--}), `revisions` lists the changes, and `comments` holds the ids of the
    comments anchored here.
    """
    current: list[str] = []
    segments: list[tuple[dict | None, list[str]]] = []
    revisions: list[dict] = []
    comments: list[str] = []

    def add(text: str, revision: dict | None) -> None:
        if revision is None or revision["type"] not in REMOVED_REVISIONS:
            current.append(text)
            ranges.text(text)
        if revision is not None:
            revision["parts"].append(text)
        if segments and segments[-1][0] is revision:
            segments[-1][1].append(text)
        else:
            segments.append((revision, [text]))

    def collect(node, revision: dict | None) -> None:
        for child in node:
            tag = child.tag
            # A text box is stored twice, as a drawing and as a legacy fallback; read it once.
            if tag == MC_FALLBACK:
                continue
            if tag == f"{W}t":
                add(child.text or "", revision)
            elif tag == f"{W}delText":
                if revision is not None and revision["type"] in REMOVED_REVISIONS:
                    add(child.text or "", revision)
            elif tag == f"{W}tab":
                add("\t", revision)
            elif tag in (f"{W}br", f"{W}cr"):
                add("\n", revision)
            elif tag in REVISION_TYPES:
                entry = {
                    "type": REVISION_TYPES[tag],
                    "author": child.get(f"{W}author"), "date": child.get(f"{W}date"), "parts": [],
                }
                revisions.append(entry)
                collect(child, entry)
            elif tag in (f"{W}commentRangeStart", f"{W}commentReference"):
                comment_id = child.get(f"{W}id")
                if comment_id is None:
                    continue
                if comment_id not in ranges.located:
                    ranges.located.add(comment_id)
                    comments.append(comment_id)
                if tag == f"{W}commentRangeStart":
                    ranges.open.setdefault(comment_id, [])
            elif tag == f"{W}commentRangeEnd":
                ranges.close(child.get(f"{W}id") or "")
            else:
                collect(child, revision)

    collect(paragraph, None)
    ranges.text("\n")
    result = {"text": "".join(current).strip(), "marked": "", "revisions": [], "comments": comments}
    for entry in revisions:
        text = "".join(entry["parts"])
        if text.strip():
            result["revisions"].append({
                "type": entry["type"], "text": text,
                **{name: entry[name] for name in ("author", "date") if entry[name]},
            })
    if result["revisions"]:
        pieces = []
        for revision, texts in segments:
            text = "".join(texts)
            if revision is None:
                pieces.append(text)
            elif text.strip():
                opening, closing = CRITIC_MARKS[revision["type"]]
                pieces.append(f"{opening}{text}{closing}")
            elif revision["type"] not in REMOVED_REVISIONS:
                pieces.append(text)
        result["marked"] = "".join(pieces).strip()
    return result


def _paragraph_text(paragraph) -> str:
    return _read_paragraph(paragraph, _Ranges())["text"]


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


def _walk(container, style_levels: dict[str, int], ranges: _Ranges):
    """Paragraphs and table rows in document order, empty ones too: an empty one
    can still hold a comment or a deletion."""
    for child in container:
        if child.tag == f"{W}p":
            read = _read_paragraph(child, ranges)
            level = _paragraph_level(child, style_levels) if read["text"] else None
            yield {"kind": "heading" if level else "paragraph", "level": level, **read}
        elif child.tag == f"{W}tbl":
            for row in child.iter(f"{W}tr"):
                cells, marked, revisions, comments = [], [], [], []
                for cell in row.findall(f"{W}tc"):
                    reads = [_read_paragraph(p, ranges) for p in cell.iter(f"{W}p")]
                    cells.append(" ".join(read["text"] for read in reads if read["text"]).replace("\n", " "))
                    shown = (read["marked"] or read["text"] for read in reads)
                    marked.append(" ".join(text for text in shown if text).replace("\n", " "))
                    for read in reads:
                        revisions += read["revisions"]
                        comments += read["comments"]
                yield {
                    "kind": "table_row", "level": None,
                    "text": " | ".join(cells) if any(cells) else "",
                    "marked": " | ".join(marked) if revisions else "",
                    "revisions": revisions, "comments": comments,
                }
        elif child.tag == f"{W}sdt":
            content = child.find(f"{W}sdtContent")
            if content is not None:
                yield from _walk(content, style_levels, ranges)


def _comments(archive: zipfile.ZipFile) -> tuple[dict[str, dict], dict[str, str]]:
    """Comments by id, and the parent of each reply (from commentsExtended.xml)."""
    data = _read_part(archive, "word/comments.xml")
    if not data:
        return {}, {}
    comments: dict[str, dict] = {}
    by_paragraph: dict[str, str] = {}
    for node in ElementTree.fromstring(data).iter(f"{W}comment"):
        comment_id = node.get(f"{W}id")
        if comment_id is None:
            continue
        paragraphs = list(node.iter(f"{W}p"))
        texts = [_paragraph_text(paragraph) for paragraph in paragraphs]
        comments[comment_id] = {
            "id": comment_id,
            **{name: node.get(f"{W}{name}") for name in ("author", "date") if node.get(f"{W}{name}")},
            "text": "\n".join(text for text in texts if text),
        }
        # commentsExtended.xml names a comment by the paraId of its last paragraph.
        for paragraph in paragraphs:
            if paragraph.get(f"{W14}paraId"):
                by_paragraph[paragraph.get(f"{W14}paraId").upper()] = comment_id
    parents: dict[str, str] = {}
    extended = _read_part(archive, "word/commentsExtended.xml")
    for entry in ElementTree.fromstring(extended).iter(f"{W15}commentEx") if extended else ():
        comment_id = by_paragraph.get((entry.get(f"{W15}paraId") or "").upper())
        if comment_id is None:
            continue
        if entry.get(f"{W15}done") in ("1", "true"):
            comments[comment_id]["resolved"] = True
        parent = by_paragraph.get((entry.get(f"{W15}paraIdParent") or "").upper())
        if parent is not None and parent != comment_id:
            parents[comment_id] = parent
    return comments, parents


def _merge(target: dict, source: dict, before: bool) -> None:
    """Carry what an empty item holds onto a neighbour with text."""
    if source["marked"]:
        own = target["marked"] or target["text"]
        target["marked"] = f"{source['marked']}\n{own}" if before else f"{own}\n{source['marked']}"
    for name in ("revisions", "comments"):
        target[name] = source[name] + target[name] if before else target[name] + source[name]


def _finish(item: dict, comments: dict[str, dict], parents: dict[str, str],
            anchors: dict[str, str]) -> None:
    """Resolve comment ids into threads; drop the annotation keys an item does not need."""
    threads = []
    for comment_id in item.pop("comments"):
        if comment_id not in comments or parents.get(comment_id) in comments:
            continue  # unknown, or a reply: replies sit under their parent
        thread = {**comments[comment_id], "anchor": anchors.get(comment_id, "")}
        replies = [dict(comments[reply]) for reply, parent in parents.items()
                   if parent == comment_id and reply in comments]
        if replies:
            thread["replies"] = replies
        threads.append(thread)
    if threads:
        item["comments"] = threads
    marked = item.pop("marked")
    if item["revisions"]:
        item["marked"] = marked
    else:
        del item["revisions"]


def docx_items(path: Path) -> list[dict]:
    """Non-empty paragraphs, headings and table rows in document order.

    Each item carries a 1-based `index`, which is the citation unit for .docx.
    The text is the document with every tracked change accepted. An item holding
    comments carries `comments`; one holding tracked changes carries `revisions`
    and `marked`, its text with the changes written in. Other items carry neither.
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
        comments, parents = _comments(archive)
    body = ElementTree.fromstring(document).find(f"{W}body")
    if body is None:
        return []
    ranges = _Ranges()
    items: list[dict] = []
    # A paragraph or row that is empty once the changes are accepted (a deleted one)
    # gets no number; what it holds goes to the item before it, or the first item.
    leading: dict | None = None
    for item in _walk(body, style_levels, ranges):
        if item["text"]:
            if leading is not None:
                _merge(item, leading, before=True)
                leading = None
            items.append(item)
        elif item["revisions"] or item["comments"]:
            if items:
                _merge(items[-1], item, before=False)
            elif leading is None:
                leading = item
            else:
                _merge(leading, item, before=False)
    for index, item in enumerate(items, 1):
        item["index"] = index
        _finish(item, comments, parents, ranges.anchors)
    return items


def docx_annotations(items: list[dict]) -> dict:
    """The comments and tracked changes of a run of items, each with its paragraph number.

    Empty for items that hold none, so a plain document gains no keys.
    """
    result: dict = {}
    for name in ("comments", "revisions"):
        found = [{"paragraph": item["index"], **entry} for item in items for entry in item.get(name, [])]
        if found:
            result[name] = found
    return result


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


def docx_render(items: list[dict], show_changes: bool = False) -> str:
    """Plain text for a run of items; headings keep their level as Markdown hashes.

    `show_changes` writes tracked changes in, as {++inserted++} and {--deleted--}.
    """
    lines = []
    for item in items:
        text = item.get("marked", item["text"]) if show_changes else item["text"]
        if item["kind"] == "heading":
            lines.append(f"{'#' * item['level']} {text}")
        else:
            lines.append(text)
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
