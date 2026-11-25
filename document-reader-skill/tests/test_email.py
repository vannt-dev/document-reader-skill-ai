import base64
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

import build_cache
import index_documents
import mail_text
import read_email
from conftest import docx_paragraph, msg_tree, write_cfb, write_docx

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def run(script, *args):
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPTS / script), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8",
    )


def docx_bytes(tmp_path):
    path = write_docx(tmp_path / "attached-spec.docx", docx_paragraph("REQ-301 Refunds within 5 days."))
    data = path.read_bytes()
    path.unlink()
    return data


def b64(data):
    return base64.encodebytes(data).decode("ascii")


# A message as a mail client writes it: a plain and an HTML body, an encoded
# subject and sender name, a Word document, an image and a forwarded message.
def alternative_eml(tmp_path):
    forwarded = (
        "From: Minh <minh@example.com>\r\nTo: Lan <lan@example.com>\r\n"
        "Subject: Old thread\r\nDate: Mon, 2 Nov 2026 08:00:00 +0700\r\n\r\n"
        "REQ-302 Keep receipts for a year.\r\n"
    )
    return (
        "From: =?UTF-8?B?Tmd1eeG7hW4gVsSDbiBMYW4=?= <lan@example.com>\r\n"
        "To: Team <team@example.com>, dev@example.com\r\n"
        "Cc: Boss <boss@example.com>\r\n"
        "Date: Tue, 3 Nov 2026 09:00:00 +0700\r\n"
        "Subject: =?UTF-8?Q?Y=C3=AAu_c=E1=BA=A7u_thanh_to=C3=A1n?=\r\n"
        "  =?UTF-8?Q?_v2?=\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="mixed"\r\n\r\n'
        "--mixed\r\n"
        'Content-Type: multipart/alternative; boundary="alt"\r\n\r\n'
        "--alt\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "Content-Transfer-Encoding: quoted-printable\r\n\r\n"
        "Ch=C3=A0o c=E1=BA=A3 nh=C3=B3m,\r\n"
        "REQ-300 Refund within 5 days.\r\n\r\n"
        "--alt\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        "<html><body><p>HTML version, not read</p></body></html>\r\n\r\n"
        "--alt--\r\n\r\n"
        "--mixed\r\n"
        "Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n"
        "Content-Disposition: attachment; filename*=UTF-8''%C4%91%E1%BA%B7c-t%E1%BA%A3.docx\r\n"
        "Content-Transfer-Encoding: base64\r\n\r\n"
        f"{b64(docx_bytes(tmp_path))}\r\n"
        "--mixed\r\n"
        "Content-Type: image/png\r\n"
        'Content-Disposition: inline; filename="logo.png"\r\n'
        "Content-Transfer-Encoding: base64\r\n\r\n"
        f"{b64(b'not really a png')}\r\n"
        "--mixed\r\n"
        "Content-Type: message/rfc822\r\n\r\n"
        f"{forwarded}\r\n"
        "--mixed--\r\n"
    ).encode("utf-8")


@pytest.fixture
def sample_eml(tmp_path):
    path = tmp_path / "checkout.eml"
    path.write_bytes(alternative_eml(tmp_path))
    return path


def test_eml_multipart_alternative_reads_the_plain_body_and_decodes_the_headers(sample_eml):
    message = mail_text.read_message(sample_eml)
    assert message["format"] == "eml"
    assert message["headers"] == {
        "from": "Nguyễn Văn Lan <lan@example.com>",
        "to": "Team <team@example.com>, dev@example.com",
        "cc": "Boss <boss@example.com>",
        "date": "Tue, 3 Nov 2026 09:00:00 +0700",
        "subject": "Yêu cầu thanh toán v2",
    }
    assert (message["body_type"], message["charset"]) == ("text/plain", "utf-8")
    assert message["body"] == "Chào cả nhóm,\nREQ-300 Refund within 5 days."
    assert "HTML version" not in "\n".join(mail_text.message_lines(message))


def test_eml_lists_attachments_with_name_type_and_size(sample_eml, tmp_path):
    summary = read_email.outline(sample_eml)
    attachments = summary["attachments"]
    assert [item["name"] for item in attachments] == ["đặc-tả.docx", "logo.png", "Old thread.eml"]
    assert [item["content_type"] for item in attachments] == [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "image/png", "message/rfc822",
    ]
    # The size is that of the decoded file, not of its base64 text.
    assert attachments[0]["size"] == len(docx_bytes(tmp_path))
    assert attachments[1]["size"] == len(b"not really a png")
    assert summary["attachment_count"] == 3
    assert summary["body_start_line"] == 7

    result = read_email.read(sample_eml, None, None, 12000)
    assert result["content"].endswith(
        "Attachments:\n"
        f"- đặc-tả.docx (application/vnd.openxmlformats-officedocument.wordprocessingml.document, {attachments[0]['size']} bytes)\n"
        "- logo.png (image/png, 16 bytes)\n"
        f"- Old thread.eml (message/rfc822, {attachments[2]['size']} bytes)"
    )
    # Off by default: no attachment is read.
    assert all("content" not in item and "not_read" not in item for item in result["attachments"])


def test_eml_attachments_are_read_only_when_asked(sample_eml):
    result = read_email.read(sample_eml, None, None, 12000, attachments=True)
    docx, image, forwarded = result["attachments"]
    assert docx["read_as"] == "docx" and "REQ-301 Refunds within 5 days." in docx["content"]
    assert image["not_read"] == "not a format the reader supports"
    assert forwarded["read_as"] == "email"
    assert "Subject: Old thread" in forwarded["content"] and "REQ-302" in forwarded["content"]


def test_eml_line_range_and_truncation(sample_eml):
    result = read_email.read(sample_eml, 5, 7, 12000)
    assert result["content"] == "Subject: Yêu cầu thanh toán v2\n\nChào cả nhóm,"
    assert result["source"] == {"start_line": 5, "end_line": 7}
    assert read_email.read(sample_eml, None, None, 10)["truncated"] is True


def test_eml_non_utf8_charsets(tmp_path):
    path = tmp_path / "legacy.eml"
    path.write_bytes(
        b"From: =?iso-8859-1?Q?Ren=E9e_Dupr=E9?= <renee@example.com>\r\n"
        b"To: =?koi8-r?B?8NLJ18XU?= <ivan@example.com>\r\n"
        b"Subject: =?windows-1252?Q?Caf=E9_=96_menu?=\r\n"
        b"Date: Wed, 4 Nov 2026 10:00:00 +0100\r\n"
        b"Content-Type: text/plain; charset=windows-1252\r\n"
        b"Content-Transfer-Encoding: quoted-printable\r\n\r\n"
        b"Cr=E8me br=FBl=E9e =80 5\r\n"
    )
    message = mail_text.read_message(path)
    assert message["headers"]["from"] == "Renée Dupré <renee@example.com>"
    assert message["headers"]["to"] == "Привет <ivan@example.com>"
    assert message["headers"]["subject"] == "Café – menu"
    assert message["body"] == "Crème brûlée € 5"
    assert message["charset"] == "windows-1252"


def test_eml_raw_8bit_headers_and_an_unknown_charset_still_read(tmp_path):
    path = tmp_path / "odd.eml"
    path.write_bytes(
        "Subject: Báo cáo tuần\r\nFrom: =?x-unknown?Q?abc?= <a@example.com>\r\n".encode("utf-8")
        + b"Content-Type: text/plain; charset=x-unknown\r\n\r\n"
        + "Nội dung".encode("utf-8") + b"\r\n"
    )
    message = mail_text.read_message(path)
    assert message["headers"]["subject"] == "Báo cáo tuần"
    assert "a@example.com" in message["headers"]["from"]
    assert message["body"] == "Nội dung"


def test_eml_html_only_body_is_read_as_text(tmp_path):
    path = tmp_path / "html.eml"
    path.write_bytes(
        b"From: a@example.com\r\nSubject: Rules\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<html><head><style>p{}</style><script>alert(1)</script></head>"
        b"<body><h2>Limits</h2><ul><li>REQ-310 At most 50 items</li></ul>"
        b"<table><tr><td>ID</td><td>Fee</td></tr></table></body></html>\r\n"
    )
    message = mail_text.read_message(path)
    assert message["body_type"] == "text/html"
    assert message["body"] == "## Limits\n- REQ-310 At most 50 items\nID | Fee"


def test_eml_without_a_body_says_so(tmp_path):
    path = tmp_path / "empty.eml"
    path.write_bytes(
        b"From: a@example.com\r\nSubject: Files only\r\n"
        b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
        b"--b\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename=a.pdf\r\n\r\n%PDF\r\n--b--\r\n"
    )
    lines = mail_text.message_lines(mail_text.read_message(path))
    assert "[the message has no text body]" in lines
    assert lines[-1] == "- a.pdf (application/pdf, 4 bytes)"


@pytest.mark.parametrize("data", [b"", b"\x00\x01\x02 binary garbage \xff\xfe", b"just some words\nand more words\n"])
def test_a_file_that_is_not_a_mail_gives_a_clear_error(tmp_path, data):
    path = tmp_path / "broken.eml"
    path.write_bytes(data)
    with pytest.raises(ValueError, match="Not an e-mail message"):
        mail_text.read_message(path)
    result = run("read_email.py", path)
    assert result.returncode == 2
    assert "error: Not an e-mail message" in result.stderr


# --- .msg ---------------------------------------------------------------------------


def filetime(year, month, day, hour):
    from datetime import datetime, timezone

    moment = datetime(year, month, day, hour, tzinfo=timezone.utc)
    seconds = (moment - datetime(1601, 1, 1, tzinfo=timezone.utc)).total_seconds()
    return struct.pack("<Q", int(seconds * 10_000_000))


@pytest.fixture
def sample_msg(tmp_path):
    pytest.importorskip("olefile")
    forwarded = msg_tree({0x0037: "Old thread", 0x0C1A: "Minh", 0x1000: "REQ-402 Keep receipts."}, header_size=24)
    tree = msg_tree(
        {
            0x0037: "Yêu cầu thanh toán", 0x0C1A: "Nguyễn Văn Lan", 0x5D01: "lan@example.com",
            0x1000: "Chào cả nhóm,\r\nREQ-400 Refund within 5 days.\r\n",
        },
        fixed={(0x0039, 0x0040): filetime(2026, 11, 3, 2)},
        recipients=[(1, "Team", "team@example.com"), (1, "Team", "team@example.com"), (2, "Boss", "boss@example.com")],
        attachments=[
            ("đặc-tả.docx", None, docx_bytes(tmp_path)),
            ("big.bin", "application/octet-stream", bytes(range(256)) * 20),
            ("Fwd: old thread", None, forwarded),
        ],
    )
    return write_cfb(tmp_path / "checkout.msg", tree)


def test_msg_headers_body_and_attachments(sample_msg, tmp_path):
    message = mail_text.read_message(sample_msg)
    assert message["format"] == "msg"
    assert message["headers"] == {
        "from": "Nguyễn Văn Lan <lan@example.com>",
        "to": "Team <team@example.com>",
        "cc": "Boss <boss@example.com>",
        "date": "Tue, 03 Nov 2026 02:00:00 +0000",
        "subject": "Yêu cầu thanh toán",
    }
    assert message["body"] == "Chào cả nhóm,\nREQ-400 Refund within 5 days."
    assert message["body_type"] == "text/plain"
    summary = read_email.outline(sample_msg)
    assert summary["attachments"] == [
        {
            "name": "đặc-tả.docx",
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "size": len(docx_bytes(tmp_path)),
        },
        # Over 4096 bytes: stored outside the mini stream.
        {"name": "big.bin", "content_type": "application/octet-stream", "size": 5120},
        {"name": "Fwd: old thread", "content_type": "application/vnd.ms-outlook", "size": None},
    ]


def test_msg_attachments_are_read_when_asked(sample_msg):
    result = read_email.read(sample_msg, None, None, 12000, attachments=True)
    docx, binary, forwarded = result["attachments"]
    assert "REQ-301" in docx["content"]
    assert binary["not_read"] == "not a format the reader supports"
    assert forwarded["read_as"] == "email" and "REQ-402 Keep receipts." in forwarded["content"]
    assert "Subject: Old thread" in forwarded["content"]


def test_msg_8bit_strings_use_the_message_codepage(tmp_path):
    pytest.importorskip("olefile")
    tree = msg_tree(
        {0x0037: "Отчёт за неделю", 0x0C1A: "Иван", 0x1000: "Привет, команда"},
        codepage="cp1251",
    )
    message = mail_text.read_message(write_cfb(tmp_path / "ru.msg", tree))
    assert message["headers"]["subject"] == "Отчёт за неделю"
    assert message["headers"]["from"] == "Иван"
    assert (message["body"], message["charset"]) == ("Привет, команда", "cp1251")


def test_msg_html_only_body_and_rtf_only_body(tmp_path):
    pytest.importorskip("olefile")
    html = '<html><head><meta charset="windows-1252"></head><body><p>Caf\xe9 rules</p></body></html>'
    tree = msg_tree({0x0037: "HTML"}, binaries={0x1013: html.encode("cp1252")})
    message = mail_text.read_message(write_cfb(tmp_path / "html.msg", tree))
    assert (message["body"], message["body_type"]) == ("Café rules", "text/html")

    tree = msg_tree({0x0037: "RTF"}, binaries={0x1009: b"\x00" * 16})
    message = mail_text.read_message(write_cfb(tmp_path / "rtf.msg", tree))
    assert message["body"] == ""
    assert message["note"] == "the body is only in RTF, which is not read"
    assert "[the body is only in RTF, which is not read]" in mail_text.message_lines(message)


def test_malformed_msg_files_give_clear_errors(tmp_path):
    pytest.importorskip("olefile")
    not_ole = tmp_path / "text.msg"
    not_ole.write_text("From: someone\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not an OLE compound file"):
        mail_text.read_message(not_ole)

    word_97 = write_cfb(tmp_path / "old-word.msg", {"WordDocument": b"\x00" * 64, "1Table": b"\x00" * 64})
    with pytest.raises(ValueError, match="without message properties"):
        mail_text.read_message(word_97)

    cut = tmp_path / "cut.msg"
    cut.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
    with pytest.raises(ValueError, match="Damaged Outlook .msg file"):
        mail_text.read_message(cut)

    result = run("read_email.py", word_97)
    assert result.returncode == 2 and "error: Not an Outlook .msg file" in result.stderr


def test_msg_without_olefile_says_how_to_install_it(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "olefile", None)
    path = tmp_path / "any.msg"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600)
    with pytest.raises(RuntimeError, match="python -m pip install olefile"):
        mail_text.read_message(path)


# --- index, cache, search, normalize ---------------------------------------------------


def test_index_and_cache_read_mail(tmp_path, sample_eml, sample_msg, manifest_for):
    result = run("index_documents.py", tmp_path)
    assert result.returncode == 0, result.stderr
    documents = {item["path"]: item for item in json.loads(result.stdout)["documents"]}
    assert documents["checkout.eml"]["type"] == "email"
    assert documents["checkout.eml"]["structure"]["headers"]["subject"] == "Yêu cầu thanh toán v2"
    assert documents["checkout.msg"]["structure"]["attachment_count"] == 3

    cache_dir = tmp_path / ".document-reader"
    manifest = manifest_for([sample_eml, sample_msg], cache_dir)
    build_cache.build(manifest, cache_dir, window=500)
    cached = json.loads((cache_dir / "cache" / "checkout-eml.json").read_text(encoding="utf-8"))
    assert [block["block_id"] for block in cached["blocks"]] == ["message@L1-13"]
    assert cached["blocks"][0]["label"] == "Yêu cầu thanh toán v2"
    assert "REQ-300 Refund within 5 days." in cached["blocks"][0]["content"]["text"]
    assert "email_attachments" not in cached

    # Asking for attachments reads the cached message again, though it did not change.
    build_cache.build(manifest, cache_dir, window=500, email_attachments=True)
    cached = json.loads((cache_dir / "cache" / "checkout-eml.json").read_text(encoding="utf-8"))
    attached = [block for block in cached["blocks"] if "attachment" in block["ref"]]
    assert {block["ref"]["attachment_name"] for block in attached} == {"đặc-tả.docx", "Old thread.eml"}
    assert any("REQ-301" in block["content"]["text"] for block in attached)
    assert attached[0]["block_id"].startswith("attachment-1/")
    assert cached["email_attachments"] == {
        "not_read": [{"name": "logo.png", "reason": "not a format the reader supports"}]
    }
    msg_cache = json.loads((cache_dir / "cache" / "checkout-msg.json").read_text(encoding="utf-8"))
    assert any("REQ-402" in block["content"]["text"] for block in msg_cache["blocks"])


def test_long_messages_are_cut_into_line_windows(tmp_path):
    path = tmp_path / "long.eml"
    path.write_bytes(b"Subject: Long\r\n\r\n" + b"".join(b"line %d\r\n" % number for number in range(1, 13)))
    blocks = mail_text.message_blocks(mail_text.read_message(path), 10)
    assert [(block["block_id"], block["label"]) for block in blocks] == [
        ("message@L1-10", "Long lines 1-10"), ("message@L11-17", "Long lines 11-17"),
    ]


def test_search_and_normalize_mail(tmp_path, sample_eml):
    result = run("search_document.py", sample_eml, "REQ-300", "--context-lines", "0")
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    assert found["type"] == "email"
    assert found["matches"] == [{"line": 8, "context_start": 8, "context_end": 8, "text": "REQ-300 Refund within 5 days."}]

    extracted = tmp_path / "extracted.json"
    assert run("read_email.py", sample_eml, "--attachments", "--output", extracted).returncode == 0
    normalized = run("normalize_output.py", extracted)
    assert normalized.returncode == 0, normalized.stderr
    blocks = json.loads(normalized.stdout)["blocks"]
    assert blocks[0]["kind"] == "text" and "REQ-300" in blocks[0]["data"]
    assert [block["source"].get("attachment") for block in blocks[1:]] == ["đặc-tả.docx", "Old thread.eml"]

    outline = tmp_path / "outline.json"
    assert run("read_email.py", sample_eml, "--outline-only", "--output", outline).returncode == 0
    normalized = run("normalize_output.py", outline)
    assert normalized.returncode == 0, normalized.stderr
    assert json.loads(normalized.stdout)["blocks"][0]["data"]["headers"]["cc"] == "Boss <boss@example.com>"
