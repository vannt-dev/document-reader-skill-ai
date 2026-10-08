import json
import subprocess

import pytest

import build_cache
import ocr
import query_cache
import read_image
import read_pdf
from conftest import text_at, write_raw_pdf

pytest.importorskip("pypdf")

LISTING = b'List of available languages in "/usr/share/tessdata/" (3):\neng\nosd\nvie\n'


def completed(stdout=b"", stderr=b"", code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


@pytest.fixture
def no_environment(monkeypatch, tmp_path):
    """A machine with no Tesseract and no settings of ours."""
    for name in ("DOCUMENT_READER_TESSERACT", "DOCUMENT_READER_TESSDATA", "DOCUMENT_READER_OCR_LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOCUMENT_READER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "programs"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    return tmp_path


@pytest.fixture
def fake_tesseract(no_environment, monkeypatch):
    """Stands in for the program: records each command and answers from `replies`."""
    program = no_environment / "tesseract.exe"
    program.write_bytes(b"")
    monkeypatch.setenv("DOCUMENT_READER_TESSERACT", str(program))
    calls = []
    replies = {"--list-langs": completed(LISTING), "--version": completed(b"tesseract 5.5.0\n leptonica-1.85\n")}

    def run(command, **options):
        calls.append(command)
        for flag, reply in replies.items():
            if flag in command:
                return reply
        return replies.get("read", completed(b"Recognised text\n\f"))

    monkeypatch.setattr(ocr.subprocess, "run", run)
    return {"program": program, "calls": calls, "replies": replies}


# --- finding the program and its data ---------------------------------------


def test_the_program_is_found_by_setting_then_path_then_the_windows_folders(no_environment, monkeypatch):
    assert ocr.find_tesseract() is None
    assert ocr.available() is False

    installed = no_environment / "programs" / "Tesseract-OCR" / "tesseract.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"")
    assert ocr.find_tesseract() == installed

    on_path = no_environment / "bin" / "tesseract"
    monkeypatch.setattr(ocr.shutil, "which", lambda name: str(on_path))
    assert ocr.find_tesseract() == on_path

    # A setting that points nowhere is a mistake to report, not to paper over
    # with whatever else is on the machine.
    monkeypatch.setenv("DOCUMENT_READER_TESSERACT", str(no_environment / "missing.exe"))
    assert ocr.find_tesseract() is None
    monkeypatch.setenv("DOCUMENT_READER_TESSERACT", str(installed))
    assert ocr.find_tesseract() == installed


def test_language_files_come_from_the_setting_or_the_skill_folder(no_environment, monkeypatch):
    assert ocr.tessdata_dir() is None

    own = no_environment / "home" / "tessdata"
    own.mkdir(parents=True)
    assert ocr.tessdata_dir() == own

    monkeypatch.setenv("DOCUMENT_READER_TESSDATA", str(no_environment / "elsewhere"))
    assert ocr.tessdata_dir() == no_environment / "elsewhere"


def test_without_the_program_every_entry_point_says_how_to_get_it(no_environment, tmp_path, capsys):
    with pytest.raises(RuntimeError, match="OCR requires Tesseract"):
        ocr.resolve_languages()

    picture = tmp_path / "scan.png"
    picture.write_bytes(b"not read")
    with pytest.raises(RuntimeError, match="winget install"):
        read_image.read(picture, 100)


# --- languages ------------------------------------------------------------


def test_installed_languages_are_read_from_the_listing(fake_tesseract):
    assert ocr.installed_languages() == ["eng", "vie"]
    assert ocr.engine_version() == "tesseract 5.5.0"

    # Older builds write the listing to stderr.
    fake_tesseract["replies"]["--list-langs"] = completed(stderr=LISTING)
    assert ocr.installed_languages() == ["eng", "vie"]


def test_the_default_is_vietnamese_and_english_whichever_are_there(fake_tesseract, monkeypatch):
    assert ocr.resolve_languages() == "vie+eng"

    fake_tesseract["replies"]["--list-langs"] = completed(b"List (2):\neng\nfra\n")
    assert ocr.resolve_languages() == "eng"

    fake_tesseract["replies"]["--list-langs"] = completed(b"List (1):\nfra\n")
    with pytest.raises(RuntimeError, match="neither Vietnamese nor English"):
        ocr.resolve_languages()
    # A setting for the machine is used where the caller names nothing.
    monkeypatch.setenv("DOCUMENT_READER_OCR_LANG", "fra")
    assert ocr.resolve_languages() == "fra"
    assert ocr.resolve_languages("fra") == "fra"


def test_a_language_asked_for_by_name_must_be_installed(fake_tesseract):
    assert ocr.resolve_languages("eng") == "eng"
    assert ocr.resolve_languages("vie,eng") == "vie+eng"

    with pytest.raises(RuntimeError, match=r"no language data for jpn \(installed: eng, vie\)"):
        ocr.resolve_languages("eng+jpn")
    for wrong in ("vie eng", "+", "../etc"):
        with pytest.raises(ValueError, match="must look like vie\\+eng"):
            ocr.resolve_languages(wrong)


# --- reading -----------------------------------------------------------------


def test_clean_drops_the_page_break_and_runs_of_blank_lines():
    assert ocr.clean("\n\nTitle  \n\n\n\nBody line\n\f") == "Title\n\nBody line"
    assert ocr.clean("\f") == ""


def test_an_image_is_read_with_the_languages_and_the_data_folder(fake_tesseract, no_environment, tmp_path):
    picture = tmp_path / "scan.png"
    picture.write_bytes(b"")
    assert ocr.image_text(picture, "vie+eng") == "Recognised text"
    assert fake_tesseract["calls"][-1] == [str(fake_tesseract["program"]), str(picture), "stdout", "-l", "vie+eng"]

    data = no_environment / "home" / "tessdata"
    data.mkdir(parents=True)
    ocr.image_text(picture, "eng")
    assert fake_tesseract["calls"][-1][:3] == [str(fake_tesseract["program"]), "--tessdata-dir", str(data)]


def test_a_failed_run_and_a_hung_one_are_reported_as_such(fake_tesseract, monkeypatch, tmp_path):
    picture = tmp_path / "scan.png"
    picture.write_bytes(b"")
    fake_tesseract["replies"]["read"] = completed(stderr=b"Estimating\nError in pixRead: not an image\n", code=1)
    with pytest.raises(RuntimeError, match="Tesseract failed on scan.png: Error in pixRead"):
        ocr.image_text(picture, "eng")

    def hang(command, **options):
        raise subprocess.TimeoutExpired(command, options["timeout"])

    monkeypatch.setattr(ocr.subprocess, "run", hang)
    with pytest.raises(RuntimeError, match="did not finish"):
        ocr.image_text(picture, "eng")

    def refuse(command, **options):
        raise PermissionError("denied")

    monkeypatch.setattr(ocr.subprocess, "run", refuse)
    with pytest.raises(RuntimeError, match="could not be started: denied"):
        ocr.image_text(picture, "eng")


def test_read_image_returns_the_text_and_how_it_was_read(fake_tesseract, tmp_path, capsys, monkeypatch):
    picture = tmp_path / "mockup.PNG"
    picture.write_bytes(b"")
    fake_tesseract["replies"]["read"] = completed("Đăng nhập\n\nLogin\n".encode("utf-8"))

    result = read_image.read(picture, 9)
    assert result["type"] == "image"
    assert result["content"] == "Đăng nhập"
    assert result["truncated"] is True
    assert result["ocr"] == {"engine": "tesseract 5.5.0", "languages": "vie+eng"}

    monkeypatch.setattr("sys.argv", ["read_image.py", str(picture), "--ocr-lang", "eng"])
    assert read_image.main() == 0
    assert json.loads(capsys.readouterr().out)["ocr"]["languages"] == "eng"

    document = tmp_path / "notes.txt"
    document.write_text("x", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["read_image.py", str(document)])
    assert read_image.main() == 2
    assert "Unsupported document type" in capsys.readouterr().err


# --- PDF pages -----------------------------------------------------------


@pytest.fixture
def mixed_pdf(tmp_path):
    """Page 1 has a text layer; pages 2 and 3 have none, as scanned pages do."""
    return write_raw_pdf(tmp_path / "contract.pdf", [text_at(72, 740, "Typed first page"), "", ""])


@pytest.fixture
def fake_pages(fake_tesseract, monkeypatch):
    """Recognition of PDF pages without rendering them: page 2 has text, page 3 is blank."""
    asked = []

    def pages_text(path, numbers, languages, dpi=ocr.DEFAULT_DPI):
        asked.append((path.name, list(numbers), languages, dpi))
        return {number: ("Scanned second page" if number == 2 else "") for number in numbers}

    monkeypatch.setattr(ocr, "pdf_pages_text", pages_text)
    return asked


def test_read_pdf_leaves_scanned_pages_unread_unless_asked(mixed_pdf, fake_pages):
    plain = read_pdf.read(mixed_pdf, None, 12000)
    assert plain["pages_without_text"] == [2, 3]
    assert "ocr" not in plain
    assert fake_pages == []

    outline = read_pdf.outline(mixed_pdf)
    assert outline["pages_without_text"] == [2, 3]
    assert outline["ocr_available"] is True


def test_read_pdf_with_ocr_reads_only_the_pages_without_text_and_marks_them(mixed_pdf, fake_pages):
    result = read_pdf.read(mixed_pdf, None, 12000, use_ocr=True, ocr_dpi=200)

    assert fake_pages == [("contract.pdf", [2, 3], "vie+eng", 200)]
    assert result["content"] == (
        "--- page 1 ---\nTyped first page\n\n--- page 2 (OCR) ---\nScanned second page"
    )
    # A page OCR found nothing on is still reported as unread.
    assert result["pages_without_text"] == [3]
    assert result["ocr"] == {"engine": "tesseract 5.5.0", "languages": "vie+eng", "pages": [2]}

    fake_pages.clear()
    only_typed = read_pdf.read(mixed_pdf, "1", 12000, use_ocr=True)
    assert fake_pages == []
    assert "ocr" not in only_typed


def test_a_pdf_with_text_everywhere_does_not_need_the_program(no_environment, tmp_path):
    typed = write_raw_pdf(tmp_path / "typed.pdf", [text_at(72, 740, "All typed")])
    assert read_pdf.read(typed, None, 12000, use_ocr=True)["content"].endswith("All typed")
    assert "ocr_available" not in read_pdf.outline(typed)

    scanned = write_raw_pdf(tmp_path / "scanned.pdf", [""])
    assert read_pdf.outline(scanned)["ocr_available"] is False
    with pytest.raises(RuntimeError, match="OCR requires Tesseract"):
        read_pdf.read(scanned, None, 12000, use_ocr=True)


def test_read_pdf_refuses_a_resolution_out_of_range(mixed_pdf, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["read_pdf.py", str(mixed_pdf), "--ocr", "--ocr-dpi", "5000"])
    assert read_pdf.main() == 2
    assert "ocr-dpi must be between 72 and 600" in capsys.readouterr().err


# --- the cache ---------------------------------------------------------------


def test_the_cache_keeps_scanned_pages_out_until_ocr_is_on(tmp_path, mixed_pdf, manifest_for, fake_pages):
    cache_dir = tmp_path / ".document-reader"
    manifest = manifest_for([mixed_pdf], cache_dir)

    index = build_cache.build(manifest, cache_dir, window=500)
    assert [block["label"] for block in index["documents"][0]["blocks"]] == ["Page 1"]
    assert fake_pages == []

    # The file has not changed, but its cache is missing the scanned pages:
    # asking for OCR reads it again.
    index = build_cache.build(manifest, cache_dir, window=500, ocr_languages="vie+eng")
    assert [block["label"] for block in index["documents"][0]["blocks"]] == ["Page 1", "Page 2 (OCR)"]
    cached = json.loads((cache_dir / "cache" / f"{index['documents'][0]['doc_id']}.json").read_text(encoding="utf-8"))
    assert cached["ocr"] == {"languages": "vie+eng"}
    assert cached["blocks"][1]["ref"] == {"page": 2, "ocr": True}

    found = query_cache.query(cache_dir, keyword="scanned second")
    assert [result["label"] for result in found["results"]] == ["Page 2 (OCR)"]

    # Once through OCR, it is not read a third time.
    fake_pages.clear()
    build_cache.build(manifest, cache_dir, window=500, ocr_languages="vie+eng")
    build_cache.build(manifest, cache_dir, window=500)
    assert fake_pages == []


def test_a_fully_scanned_pdf_says_what_would_read_it(tmp_path, manifest_for, fake_pages):
    scanned = write_raw_pdf(tmp_path / "scan.pdf", ["", ""])
    cache_dir = tmp_path / ".document-reader"
    manifest = manifest_for([scanned], cache_dir)

    index = build_cache.build(manifest, cache_dir, window=500)
    assert "needs OCR" in index["documents"][0]["error"]
    assert "build_cache.py --ocr" in index["documents"][0]["error"]

    index = build_cache.build(manifest, cache_dir, window=500, ocr_languages="eng")
    assert "error" not in index["documents"][0]
    assert [block["label"] for block in index["documents"][0]["blocks"]] == ["Page 2 (OCR)"]


def test_build_cache_stops_before_reading_when_ocr_cannot_run(tmp_path, mixed_pdf, manifest_for, no_environment, monkeypatch, capsys):
    cache_dir = tmp_path / ".document-reader"
    manifest = manifest_for([mixed_pdf], cache_dir)
    monkeypatch.setattr("sys.argv", [
        "build_cache.py", "--manifest", str(manifest), "--cache-dir", str(cache_dir), "--ocr",
    ])

    assert build_cache.main() == 2
    assert "OCR requires Tesseract" in capsys.readouterr().err
    assert not (cache_dir / "index.json").exists()


# --- with the real program ----------------------------------------------------


def picture_of(lines, path):
    """A white page with the lines printed large, the way a clean scan looks."""
    image_module = pytest.importorskip("PIL.Image")
    draw_module = pytest.importorskip("PIL.ImageDraw")
    font_module = pytest.importorskip("PIL.ImageFont")
    font = font_module.load_default(size=48)
    image = image_module.new("RGB", (1400, 140 + 110 * len(lines)), "white")
    draw = draw_module.Draw(image)
    for row, line in enumerate(lines):
        draw.text((70, 70 + 110 * row), line, fill="black", font=font)
    image.save(path)
    return path


needs_tesseract = pytest.mark.skipif(not ocr.available(), reason="Tesseract is not installed")


@needs_tesseract
def test_real_an_image_is_read(tmp_path):
    if "eng" not in ocr.installed_languages():
        pytest.skip("Tesseract has no English data")
    picture = picture_of(["Invoice number 48213", "Payment is due within 30 days"], tmp_path / "invoice.png")

    result = read_image.read(picture, 12000, "eng")

    assert "Invoice number 48213" in result["content"]
    assert "Payment is due within 30 days" in result["content"]
    assert result["ocr"]["engine"].startswith("tesseract")


@needs_tesseract
def test_real_a_scanned_pdf_is_read_page_by_page_and_cached(tmp_path, manifest_for):
    pytest.importorskip("pypdfium2")
    if "eng" not in ocr.installed_languages():
        pytest.skip("Tesseract has no English data")
    image_module = pytest.importorskip("PIL.Image")
    first = picture_of(["Terms of delivery", "Goods ship within 5 working days"], tmp_path / "p1.png")
    second = picture_of(["Returns are accepted for 14 days"], tmp_path / "p2.png")
    scan = tmp_path / "terms.pdf"
    # A PDF made of pictures only: what a scanner produces.
    image_module.open(first).save(scan, save_all=True, append_images=[image_module.open(second)])
    assert read_pdf.outline(scan)["pages_without_text"] == [1, 2]

    result = read_pdf.read(scan, None, 12000, use_ocr=True, ocr_lang="eng")
    assert "--- page 1 (OCR) ---" in result["content"]
    assert "Goods ship within 5 working days" in result["content"]
    assert "Returns are accepted for 14 days" in result["content"]
    assert result["pages_without_text"] == []
    assert result["ocr"]["pages"] == [1, 2]

    only_second = read_pdf.read(scan, "2", 12000, use_ocr=True, ocr_lang="eng")
    assert "Terms of delivery" not in only_second["content"]
    assert only_second["ocr"]["pages"] == [2]

    cache_dir = tmp_path / ".document-reader"
    build_cache.build(manifest_for([scan], cache_dir), cache_dir, window=500, ocr_languages="eng")
    found = query_cache.query(cache_dir, keyword="accepted for 14 days")
    assert [item["label"] for item in found["results"]] == ["Page 2 (OCR)"]
