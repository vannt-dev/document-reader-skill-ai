"""Text extraction for e-mail files: .eml (RFC 822 / MIME) and Outlook .msg.

.eml needs only the standard library. .msg is an OLE compound file and is read
with `olefile` (BSD licence), an optional dependency: without it a .msg gives a
clear error and every other format still reads.

Read-only: nothing in a message is run or fetched, and attachments stay in
memory. A message comes out as lines:

    From: Lan <lan@example.com>
    To: ...
    Cc: ...            (only when the message has one)
    Date: ...
    Subject: ...

    <the body: text/plain when there is one, else the HTML body as text>

    Attachments:
    - spec.docx (application/vnd...document, 12345 bytes)
"""

from __future__ import annotations

import codecs
import io
import mimetypes
import re
import struct
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.policy import Compat32, compat32
from email.utils import format_datetime
from pathlib import Path

from common import decode_text

# A mail file larger than this is refused rather than read into memory.
MAX_MAIL_BYTES = 64 * 1024 * 1024
# A message inside a message inside a message ... is listed, not parsed, below this depth.
MAX_NESTING = 3
HEADER_NAMES = ("from", "to", "cc", "date", "subject")
SPACES = re.compile(r"\s+")
# A file holding none of these is not a mail, whatever the parser made of it.
MAIL_HEADERS = ("from", "to", "cc", "subject", "date", "message-id", "received", "mime-version", "sender")
MSG_HINT = "Outlook .msg reading requires olefile: python -m pip install olefile"


# --- output -------------------------------------------------------------------


def message_lines(message: dict) -> list[str]:
    """The message as the numbered lines that reading, search and the cache cite."""
    headers = message["headers"]
    lines = [
        f"{name.capitalize()}: {headers[name] or ''}".rstrip()
        for name in HEADER_NAMES if name != "cc" or headers.get("cc")
    ]
    lines.append("")
    body = message["body"].splitlines()
    if body:
        lines += body
    else:
        lines.append(f"[{message.get('note') or 'no text body'}]")
    if message["attachments"]:
        lines += ["", "Attachments:"]
        lines += [f"- {attachment_label(item)}" for item in message["attachments"]]
    return lines


def attachment_label(item: dict) -> str:
    details = [item["content_type"] or "unknown type"]
    if item["size"] is not None:
        details.append(f"{item['size']} bytes")
    return f"{item['name']} ({', '.join(details)})"


def attachment_summary(item: dict) -> dict:
    """An attachment as JSON: no bytes."""
    return {"name": item["name"], "content_type": item["content_type"], "size": item["size"]}


def message_blocks(message: dict, window: int) -> list[dict]:
    """Cache blocks of a message, cited by line; a long message is cut every `window` lines."""
    lines = message_lines(message)
    subject = message["headers"]["subject"] or "(no subject)"
    blocks = []
    for start in range(1, len(lines) + 1, window):
        end = min(start + window - 1, len(lines))
        blocks.append({
            "block_id": f"message@L{start}-{end}",
            "ref": {"lines": [start, end]},
            "label": subject if len(lines) <= window else f"{subject} lines {start}-{end}",
            "content": {"text": "\n".join(lines[start - 1:end])},
        })
    return blocks


# --- reading attachments ---------------------------------------------------------------

# Attachments are read only when asked for, and within these limits.
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENTS_READ = 20


def attachment_documents(message: dict, window: int) -> list[dict]:
    """Read the attachments that are themselves documents the reader supports.

    One entry an attachment: {"attachment": n, "name", "type", "blocks"} when read,
    or {"attachment": n, "name", "not_read": reason}. A mail attached to the mail
    is read as a message, but its own attachments are only listed.
    """
    import tempfile

    from common import DOCUMENT_TYPES

    results = []
    with tempfile.TemporaryDirectory(prefix="document-reader-mail-", ignore_cleanup_errors=True) as folder:
        for number, item in enumerate(message["attachments"], 1):
            entry = {"attachment": number, "name": item["name"]}
            results.append(entry)
            suffix = Path(item["name"]).suffix.lower()
            if item["content_type"] == "message/rfc822" and suffix not in {".eml", ".msg"}:
                suffix = ".eml"
            doc_type = "email" if "message" in item else DOCUMENT_TYPES.get(suffix)
            if number > MAX_ATTACHMENTS_READ:
                entry["not_read"] = f"only the first {MAX_ATTACHMENTS_READ} attachments are read"
            elif doc_type is None:
                entry["not_read"] = "not a format the reader supports"
            elif (item["size"] or 0) > MAX_ATTACHMENT_BYTES:
                entry["not_read"] = f"larger than {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB"
            elif "message" in item and item["message"] is None:
                entry["not_read"] = "nested too deeply"
            elif "message" not in item and not item["data"]:
                entry["not_read"] = "empty"
            else:
                entry["type"] = doc_type
                try:
                    entry["blocks"] = _attachment_blocks(item, doc_type, suffix, Path(folder), number, window)
                except Exception as exc:  # noqa: BLE001 - one bad attachment must not hide the others
                    del entry["type"]
                    entry["not_read"] = f"error: {exc}"
    return results


def _attachment_blocks(item: dict, doc_type: str, suffix: str, folder: Path, number: int, window: int) -> list[dict]:
    if doc_type == "email":
        inner = item.get("message") or parse_any(item["data"], depth=1)
        return message_blocks(inner, window)
    import build_cache

    # The attachment's own name never becomes a path: only its known suffix is kept.
    source = folder / f"attachment-{number}{suffix}"
    source.write_bytes(item["data"])
    try:
        return build_cache.extract_blocks(source, doc_type, window)
    finally:
        try:
            source.unlink()
        except OSError:
            pass


def blocks_text(blocks: list[dict]) -> str:
    """Blocks as plain text: each under its label, tables as `cell | cell` rows."""
    parts = []
    for block in blocks:
        content = block["content"]
        if "rows" in content:
            rows = [content.get("headers") or []] + [row["cells"] for row in content["rows"]]
            body = "\n".join(" | ".join("" if cell is None else str(cell) for cell in row) for row in rows)
        else:
            body = content.get("text", "")
        parts.append(f"[{block['label']}]\n{body}")
    return "\n\n".join(parts)


# --- entry point --------------------------------------------------------------------


def read_message(path: Path) -> dict:
    """The parsed message of an .eml or .msg file.

    {"format", "headers": {from, to, cc, date, subject}, "body", "body_type",
     "charset", "note"?, "attachments": [{name, content_type, size, data, message?}]}
    An attachment's `data` is its bytes (None for an Outlook message stored inside
    the message, which comes parsed as `message` instead).
    """
    if path.stat().st_size > MAX_MAIL_BYTES:
        raise ValueError(f"Mail file is larger than {MAX_MAIL_BYTES // (1024 * 1024)} MB; refusing to read it")
    data = path.read_bytes()
    if path.suffix.lower() == ".msg":
        return parse_msg(data)
    return parse_eml(data)


def parse_any(data: bytes, depth: int = 0) -> dict:
    """An attached mail of either kind, told apart by its first bytes."""
    if data.startswith(OLE_SIGNATURE):
        return parse_msg(data, depth)
    return parse_eml(data)


# --- .eml ---------------------------------------------------------------------------


class _RawHeaders(Compat32):
    """compat32, but a header comes back as written: raw 8-bit bytes stay as
    surrogates instead of being turned into U+FFFD, so `_header` can decode them."""

    def header_fetch_parse(self, name, value):
        return value


def parse_eml(data: bytes) -> dict:
    # compat32 never raises on a bad header or an unknown charset: every value is
    # decoded here, with a fallback, the same way on every Python version.
    message = message_from_bytes(data, policy=_RawHeaders())
    if not any(message.get(name) is not None for name in MAIL_HEADERS):
        raise ValueError("Not an e-mail message: no From, To, Subject or Date header found")
    headers = {name: _header(message.get(name)) for name in HEADER_NAMES}
    bodies: list[Message] = []
    parts: list[Message] = []
    _collect(message, bodies, parts)
    texts, body_type, charset = [], None, None
    for part in bodies:
        payload = _payload(part)
        text, encoding = decode_text(payload, part.get_content_charset())
        if part.get_content_type() == "text/html":
            text = html_to_text(text)
        texts.append(text.replace("\r\n", "\n").replace("\r", "\n").strip("\n"))
        if body_type is None:
            body_type, charset = part.get_content_type(), encoding
    result = {
        "format": "eml", "headers": headers,
        "body": "\n\n".join(text for text in texts if text),
        "body_type": body_type, "charset": charset,
        "attachments": [_eml_attachment(part, number) for number, part in enumerate(parts, 1)],
    }
    if not bodies:
        result["note"] = "the message has no text body"
    return result


def _collect(part: Message, bodies: list[Message], attachments: list[Message]) -> None:
    """Sort the leaves of a MIME tree into body parts and attachments.

    Of a multipart/alternative, only the branch holding text/plain (else
    text/html) is read; the other branches are the same body in another form.
    """
    content_type = part.get_content_type()
    if content_type == "message/rfc822":
        attachments.append(part)
        return
    if part.is_multipart():
        children = [child for child in part.get_payload() if isinstance(child, Message)]
        if content_type == "multipart/alternative" and children:
            children = [max(children, key=_alternative_rank)]
        for child in children:
            _collect(child, bodies, attachments)
        return
    inline = part.get_content_disposition() != "attachment" and not part.get_filename()
    if inline and content_type in {"text/plain", "text/html"}:
        bodies.append(part)
    else:
        attachments.append(part)


def _alternative_rank(part: Message) -> int:
    """2 for a branch holding text/plain, 1 for text/html; the first best wins on a tie."""
    types = {leaf.get_content_type() for leaf in part.walk()}
    return 2 if "text/plain" in types else 1 if "text/html" in types else 0


def _eml_attachment(part: Message, number: int) -> dict:
    content_type = part.get_content_type()
    if content_type == "message/rfc822":
        inner = part.get_payload(0) if part.is_multipart() else None
        try:
            data = inner.as_bytes() if isinstance(inner, Message) else _payload(part)
        except Exception:  # noqa: BLE001 - a broken inner message still gets listed
            data = b""
        subject = _header(inner.get("subject")) if isinstance(inner, Message) else None
        name = _header(part.get_filename()) or _named(subject, ".eml", number)
    else:
        data = _payload(part)
        name = _header(part.get_filename()) or _named(None, mimetypes.guess_extension(content_type) or "", number)
    return {"name": name, "content_type": content_type, "size": len(data), "data": data}


def _named(stem: str | None, suffix: str, number: int) -> str:
    stem = SPACES.sub(" ", stem or "").strip()[:80] or f"attachment-{number}"
    return stem if stem.lower().endswith(suffix) else stem + suffix


def _payload(part: Message) -> bytes:
    """The decoded bytes of a leaf part (quoted-printable and base64 undone)."""
    try:
        data = part.get_payload(decode=True)
    except Exception:  # noqa: BLE001 - damaged base64 still yields what can be read
        data = None
    if isinstance(data, bytes):
        return data
    raw = part.get_payload()
    return raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else b""


def _header(value) -> str | None:
    """A header's text with encoded words (=?UTF-8?B?...?=) decoded and folding undone."""
    if value is None:
        return None
    raw = str(value)
    if any("\udc80" <= char <= "\udcff" for char in raw):
        # Raw 8-bit bytes in a header, which the parser kept as surrogates.
        raw = decode_text(raw.encode("utf-8", "surrogateescape"))[0]
    try:
        text = str(make_header(decode_header(raw)))
    except Exception:  # noqa: BLE001 - an unknown charset or a broken encoded word
        text = _decode_words(raw)
    return SPACES.sub(" ", text).strip() or None


def _decode_words(raw: str) -> str:
    try:
        parts = decode_header(raw)
    except Exception:  # noqa: BLE001
        return raw
    return "".join(
        decode_text(value, charset)[0] if isinstance(value, bytes) else value
        for value, charset in parts
    )


def html_to_text(html: str) -> str:
    from doc_text import docx_render
    from html_text import html_text_document

    return docx_render(html_text_document(html)["items"])


# --- .msg ---------------------------------------------------------------------------

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
PROPERTIES = "__properties_version1.0"
RECIPIENT_PREFIX = "__recip_version1.0_#"
ATTACHMENT_PREFIX = "__attach_version1.0_#"
EMBEDDED_MESSAGE = "__substg1.0_3701000D"
PT_LONG, PT_SYSTIME, PT_STRING8, PT_UNICODE, PT_BINARY = 0x0003, 0x0040, 0x001E, 0x001F, 0x0102
# MS-OXMSG: the property stream starts with a header of this many bytes.
TOP_HEADER, EMBEDDED_HEADER, CHILD_HEADER = 32, 24, 8
RECIPIENT_FIELDS = {1: "to", 2: "cc"}


def parse_msg(data: bytes, depth: int = 0) -> dict:
    try:
        import olefile
    except ImportError as exc:
        raise RuntimeError(MSG_HINT) from exc
    if not data.startswith(OLE_SIGNATURE):
        raise ValueError("Not an Outlook .msg file: it is not an OLE compound file")
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - olefile raises several kinds on a damaged file
        raise ValueError(f"Damaged Outlook .msg file: {exc}") from exc
    try:
        names = {"/".join(entry) for entry in ole.listdir(streams=True, storages=True)}
        if PROPERTIES not in names or not any(name.startswith("__substg1.0_") for name in names):
            raise ValueError(
                "Not an Outlook .msg file: an OLE compound file without message properties "
                "(an old .doc or .xls?)"
            )
        return _MsgReader(ole, names).message([], TOP_HEADER, depth)
    except (ValueError, RuntimeError):
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Damaged Outlook .msg file: {exc}") from exc
    finally:
        ole.close()


class _MsgReader:
    def __init__(self, ole, names: set[str]) -> None:
        self.ole = ole
        self.names = names

    def _stream(self, path: list[str]) -> bytes | None:
        name = "/".join(path)
        if name not in self.names:
            return None
        return self.ole.openstream(name).read()

    def _children(self, prefix: list[str], start: str) -> list[list[str]]:
        joined = "/".join(prefix) + "/" if prefix else ""
        found = sorted(
            name for name in self.names
            if name.startswith(joined + start) and "/" not in name[len(joined):]
        )
        return [name.split("/") for name in found]

    def _fixed(self, prefix: list[str], header: int) -> dict[int, tuple[int, bytes]]:
        """Fixed-length properties: id -> (type, 8 value bytes)."""
        data = self._stream(prefix + [PROPERTIES]) or b""
        values = {}
        for offset in range(header, len(data) - 15, 16):
            tag, _flags, value = struct.unpack_from("<II8s", data, offset)
            values[tag >> 16] = (tag & 0xFFFF, value)
        return values

    def _string(self, prefix: list[str], prop: int, codepage: str) -> str | None:
        data = self._stream(prefix + [f"__substg1.0_{prop:04X}{PT_UNICODE:04X}"])
        if data is not None:
            return data.decode("utf-16-le", errors="replace").split("\x00", 1)[0]
        data = self._stream(prefix + [f"__substg1.0_{prop:04X}{PT_STRING8:04X}"])
        if data is not None:
            return data.split(b"\x00", 1)[0].decode(codepage, errors="replace")
        return None

    def _binary(self, prefix: list[str], prop: int) -> bytes | None:
        return self._stream(prefix + [f"__substg1.0_{prop:04X}{PT_BINARY:04X}"])

    def message(self, prefix: list[str], header: int, depth: int) -> dict:
        fixed = self._fixed(prefix, header)
        codepage = _codepage(fixed, 0x3FFD) or _codepage(fixed, 0x3FDE) or "cp1252"

        def text(prop: int, where: list[str] = prefix) -> str | None:
            value = self._string(where, prop, codepage)
            return (SPACES.sub(" ", value).strip() or None) if value is not None else None

        recipients: dict[str, list[str]] = {"to": [], "cc": []}
        for storage in self._children(prefix, RECIPIENT_PREFIX):
            kind = _long(self._fixed(storage, CHILD_HEADER), 0x0C15)
            email = text(0x39FE, storage) or text(0x3003, storage)
            address = _address(text(0x3001, storage), email)
            # Outlook may store the same recipient twice; list it once.
            if kind in RECIPIENT_FIELDS and address not in recipients[RECIPIENT_FIELDS[kind]]:
                recipients[RECIPIENT_FIELDS[kind]].append(address)
        transport = self._string(prefix, 0x007D, codepage)
        headers = {
            "from": _address(
                text(0x0C1A) or text(0x0042),
                text(0x5D01) or _smtp(text(0x0C1F)) or _smtp(text(0x0065)),
            ) or None,
            "to": ", ".join(filter(None, recipients["to"])) or text(0x0E04),
            "cc": ", ".join(filter(None, recipients["cc"])) or text(0x0E03),
            "date": _transport_date(transport) or _filetime(fixed, 0x0039) or _filetime(fixed, 0x0E06),
            "subject": text(0x0037),
        }
        result = {"format": "msg", "headers": headers, "body": "", "body_type": None, "charset": None}
        body = self._string(prefix, 0x1000, codepage)
        if body and body.strip():
            result.update(body=body.replace("\r\n", "\n").strip("\n"), body_type="text/plain",
                          charset="utf-16-le" if self._stream(prefix + ["__substg1.0_1000001F"]) is not None else codepage)
        else:
            html = self._binary(prefix, 0x1013)
            html_text = None
            if html is not None:
                from html_text import META_CHARSET

                declared = META_CHARSET.search(html[:4096])
                html_text, encoding = decode_text(
                    html, declared.group(1).decode("ascii") if declared else _codepage(fixed, 0x3FDE)
                )
            else:
                html_text = self._string(prefix, 0x1013, codepage)
                encoding = codepage
            if html_text and html_text.strip():
                result.update(body=html_to_text(html_text), body_type="text/html", charset=encoding)
            elif self._binary(prefix, 0x1009) is not None:
                result["note"] = "the body is only in RTF, which is not read"
            else:
                result["note"] = "the message has no text body"
        result["attachments"] = [
            self._attachment(storage, number, codepage, depth)
            for number, storage in enumerate(self._children(prefix, ATTACHMENT_PREFIX), 1)
        ]
        return result

    def _attachment(self, storage: list[str], number: int, codepage: str, depth: int) -> dict:
        fixed = self._fixed(storage, CHILD_HEADER)
        name = None
        for prop in (0x3707, 0x3704, 0x3001):
            value = self._string(storage, prop, codepage)
            if value and value.strip():
                name = value.strip()
                break
        content_type = (self._string(storage, 0x370E, codepage) or "").strip().lower() or None
        if "/".join(storage + [EMBEDDED_MESSAGE]) in self.names:
            inner = None
            if depth < MAX_NESTING:
                inner = self.message(storage + [EMBEDDED_MESSAGE], EMBEDDED_HEADER, depth + 1)
            subject = inner["headers"]["subject"] if inner else None
            return {
                "name": name or _named(subject, ".msg", number),
                "content_type": content_type or "application/vnd.ms-outlook",
                "size": _long(fixed, 0x0E20), "data": None, "message": inner,
            }
        data = self._binary(storage, 0x3701)
        if not content_type and name:
            content_type = mimetypes.guess_type(name)[0]
        return {
            "name": name or f"attachment-{number}",
            "content_type": content_type or "application/octet-stream",
            "size": len(data) if data is not None else _long(fixed, 0x0E20),
            "data": data,
        }


def _long(fixed: dict, prop: int) -> int | None:
    entry = fixed.get(prop)
    if not entry or entry[0] != PT_LONG:
        return None
    return struct.unpack("<i", entry[1][:4])[0]


def _codepage(fixed: dict, prop: int) -> str | None:
    number = _long(fixed, prop)
    if not number:
        return None
    name = "utf-8" if number == 65001 else f"cp{number}"
    try:
        codecs.lookup(name)
    except LookupError:
        return None
    return name


def _filetime(fixed: dict, prop: int) -> str | None:
    entry = fixed.get(prop)
    if not entry or entry[0] != PT_SYSTIME:
        return None
    ticks = struct.unpack("<Q", entry[1])[0]
    if not ticks:
        return None
    try:
        moment = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks // 10)
    except OverflowError:
        return None
    return format_datetime(moment)


def _transport_date(transport: str | None) -> str | None:
    """The Date header of the internet headers Outlook keeps for a received message:
    it holds the sender's time zone, which the stored time has lost."""
    if not transport:
        return None
    from email.parser import HeaderParser

    try:
        return _header(HeaderParser(policy=compat32).parsestr(transport, headersonly=True).get("date"))
    except Exception:  # noqa: BLE001
        return None


def _smtp(value: str | None) -> str | None:
    """An address only when it is an SMTP one, not an Exchange "/O=..." path."""
    return value if value and "@" in value and not value.startswith("/") else None


def _address(name: str | None, email: str | None) -> str:
    if name and email and name != email:
        return f"{name} <{email}>"
    return name or email or ""
