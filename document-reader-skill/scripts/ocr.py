"""Text recognition (OCR) for scanned PDF pages and images.

Optional: needs the Tesseract program on the machine, which the rest of the
skill does not. Reading a PDF page this way also needs pypdfium2 and Pillow to
turn the page into a picture; both come with pdfplumber.

Where things are looked for:

* the program: `DOCUMENT_READER_TESSERACT`, then `tesseract` on PATH, then the
  folders the Windows installer uses;
* its language files: `DOCUMENT_READER_TESSDATA`, then
  `<DOCUMENT_READER_HOME or ~/.document-reader>/tessdata` when that folder
  exists, then wherever the program itself looks;
* the languages to read: `DOCUMENT_READER_OCR_LANG` (for example `vie+eng`),
  else Vietnamese and English, whichever of the two are installed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

INSTALL_HINT = (
    "OCR requires Tesseract: winget install UB-Mannheim.TesseractOCR (Windows), "
    "brew install tesseract tesseract-lang (macOS) or apt install tesseract-ocr tesseract-ocr-vie "
    "(Debian/Ubuntu); or set DOCUMENT_READER_TESSERACT to the program's path"
)
RENDER_HINT = "OCR of a PDF page requires pypdfium2 and Pillow: python -m pip install pdfplumber"

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
DEFAULT_LANGUAGES = ("vie", "eng")
DEFAULT_DPI = 300
# The longest side a page is rendered to, in pixels: an A4 page at 300 dpi is
# 3508. A poster-sized page at that resolution would be a picture of hundreds of
# megabytes, with letters too large for Tesseract to read well.
MAX_SIDE = 4000
# A page of dense text takes a few seconds; a minute means something is wrong.
TIMEOUT_SECONDS = 120

_LANGUAGE = re.compile(r"^[A-Za-z0-9_]+$")


def find_tesseract() -> Path | None:
    """The Tesseract program, or None when it is not on this machine."""
    configured = os.environ.get("DOCUMENT_READER_TESSERACT")
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_file() else None
    on_path = shutil.which("tesseract")
    if on_path:
        return Path(on_path)
    for root in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if not root:
            continue
        for folder in ("Tesseract-OCR", "Programs/Tesseract-OCR"):
            candidate = Path(root) / folder / "tesseract.exe"
            if candidate.is_file():
                return candidate
    return None


def available() -> bool:
    return find_tesseract() is not None


def tessdata_dir() -> Path | None:
    """A folder of language files to use instead of the program's own, if any."""
    configured = os.environ.get("DOCUMENT_READER_TESSDATA")
    if configured:
        return Path(configured).expanduser()
    home = os.environ.get("DOCUMENT_READER_HOME")
    folder = (Path(home).expanduser() if home else Path.home() / ".document-reader") / "tessdata"
    return folder if folder.is_dir() else None


def _run(arguments: list[str]) -> subprocess.CompletedProcess:
    program = find_tesseract()
    if program is None:
        raise RuntimeError(INSTALL_HINT)
    data = tessdata_dir()
    where = ["--tessdata-dir", str(data)] if data is not None else []
    command = [str(program), *where, *arguments]
    try:
        return subprocess.run(command, capture_output=True, timeout=TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Tesseract did not finish within {TIMEOUT_SECONDS} seconds") from exc
    except OSError as exc:
        raise RuntimeError(f"Tesseract could not be started: {exc}") from exc


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def engine_version() -> str:
    """Such as "tesseract 5.5.0"."""
    result = _run(["--version"])
    # Older builds print the version on stderr.
    lines = (_decode(result.stdout) or _decode(result.stderr)).splitlines()
    return lines[0].strip() if lines else "tesseract"


def installed_languages() -> list[str]:
    result = _run(["--list-langs"])
    lines = (_decode(result.stdout) + "\n" + _decode(result.stderr)).splitlines()
    # The first line is a sentence about where the list comes from.
    return sorted({line.strip() for line in lines if _LANGUAGE.match(line.strip()) and line.strip() != "osd"})


def resolve_languages(requested: str | None = None) -> str:
    """The `-l` value to read with, checked against what is installed.

    A language asked for by name must be there: reading Vietnamese with the
    English data returns confident nonsense, which is worse than an error.
    """
    installed = installed_languages()
    asked = requested or os.environ.get("DOCUMENT_READER_OCR_LANG")
    if asked:
        names = [name for name in asked.replace(",", "+").split("+") if name]
        if not names or not all(_LANGUAGE.match(name) for name in names):
            raise ValueError(f"OCR languages must look like vie+eng, not {asked!r}")
        missing = [name for name in names if name not in installed]
        if missing:
            raise RuntimeError(
                f"Tesseract has no language data for {', '.join(missing)} "
                f"(installed: {', '.join(installed) or 'none'}); add {missing[0]}.traineddata to its tessdata folder"
            )
        return "+".join(names)
    names = [name for name in DEFAULT_LANGUAGES if name in installed]
    if not names:
        raise RuntimeError(
            f"Tesseract has neither Vietnamese nor English language data (installed: {', '.join(installed) or 'none'})"
        )
    return "+".join(names)


def clean(text: str) -> str:
    """Recognised text with the page-break mark and the runs of blank lines taken out."""
    lines = [line.rstrip() for line in text.replace("\f", "").splitlines()]
    kept: list[str] = []
    for line in lines:
        if line or (kept and kept[-1]):
            kept.append(line)
    return "\n".join(kept).strip()


def image_text(path: Path, languages: str) -> str:
    """The text Tesseract reads in the picture at `path`."""
    result = _run([str(path), "stdout", "-l", languages])
    if result.returncode != 0:
        detail = _decode(result.stderr).strip().splitlines()
        raise RuntimeError(f"Tesseract failed on {path.name}: {detail[-1] if detail else result.returncode}")
    return clean(_decode(result.stdout))


def pdf_pages_text(path: Path, numbers: list[int], languages: str, dpi: int = DEFAULT_DPI) -> dict[int, str]:
    """The text of the given 1-based pages of a PDF, each read from a picture of the page."""
    if not numbers:
        return {}
    try:
        import pypdfium2
    except ImportError as exc:
        raise RuntimeError(RENDER_HINT) from exc

    texts: dict[int, str] = {}
    document = pypdfium2.PdfDocument(str(path))
    try:
        with tempfile.TemporaryDirectory(prefix="document-reader-ocr-") as folder:
            for number in numbers:
                page = document[number - 1]
                try:
                    # A PDF page is measured in points, 72 to the inch.
                    scale = min(dpi / 72, MAX_SIDE / max(page.get_size()))
                    picture = page.render(scale=scale).to_pil()
                except ImportError as exc:
                    raise RuntimeError(RENDER_HINT) from exc
                finally:
                    page.close()
                target = Path(folder) / f"page-{number}.png"
                picture.save(target)
                texts[number] = image_text(target, languages)
    finally:
        document.close()
    return texts


def describe(languages: str, pages: list[int] | None = None) -> dict:
    """What a result says about how its text was recognised."""
    info: dict = {"engine": engine_version(), "languages": languages}
    if pages is not None:
        info["pages"] = pages
    return info
