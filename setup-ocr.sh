#!/bin/sh
# Optional setup for reading scanned PDF pages and images (OCR).
#
#   sh setup-ocr.sh            # Vietnamese and English
#   sh setup-ocr.sh vie eng jpn
#
# 1. Checks that the Tesseract program is on the machine. It is not installed
#    for you: that needs your package manager, and usually sudo.
# 2. Downloads the language files into <runtime>/tessdata, where the skill
#    looks first. Nothing is written into the Tesseract installation.
set -eu

RUNTIME_ROOT=${DOCUMENT_READER_HOME:-"$HOME/.document-reader"}
TESSDATA="$RUNTIME_ROOT/tessdata"
DATA_SOURCE="https://github.com/tesseract-ocr/tessdata_fast/raw/main"

if [ "$#" -eq 0 ]; then
  set -- vie eng
fi

for language in "$@"; do
  case "$language" in
    *[!A-Za-z0-9_]* | "")
      echo "ERROR: not a Tesseract language code: $language" >&2
      exit 2
      ;;
  esac
done

if [ -n "${DOCUMENT_READER_TESSERACT:-}" ]; then
  TESSERACT=$DOCUMENT_READER_TESSERACT
elif command -v tesseract >/dev/null 2>&1; then
  TESSERACT=$(command -v tesseract)
else
  TESSERACT=""
fi

if [ -z "$TESSERACT" ] || [ ! -x "$TESSERACT" ]; then
  echo "ERROR: Tesseract is not installed. Install it and run this script again:" >&2
  echo "  macOS:          brew install tesseract" >&2
  echo "  Debian/Ubuntu:  sudo apt install tesseract-ocr" >&2
  echo "  Fedora:         sudo dnf install tesseract" >&2
  echo "Or set DOCUMENT_READER_TESSERACT to the program's path." >&2
  exit 3
fi
echo "Tesseract: $TESSERACT"

if command -v curl >/dev/null 2>&1; then
  fetch() { curl -fLsS -o "$2" "$1"; }
elif command -v wget >/dev/null 2>&1; then
  fetch() { wget -q -O "$2" "$1"; }
else
  echo "ERROR: curl or wget is required to download the language files." >&2
  exit 2
fi

mkdir -p "$TESSDATA"
for language in "$@"; do
  target="$TESSDATA/$language.traineddata"
  if [ -f "$target" ]; then
    echo "Language file already there: $language"
    continue
  fi
  echo "Downloading language file: $language"
  # To a temporary name first, so an interrupted download never leaves a
  # half-written file that Tesseract would then fail to load.
  if ! fetch "$DATA_SOURCE/$language.traineddata" "$target.part"; then
    rm -f "$target.part"
    echo "ERROR: could not download $language.traineddata (is '$language' a Tesseract language code?)" >&2
    exit 4
  fi
  mv "$target.part" "$target"
done

listing=$("$TESSERACT" --tessdata-dir "$TESSDATA" --list-langs 2>&1 || true)
for language in "$@"; do
  if ! printf '%s\n' "$listing" | grep -qx "$language"; then
    echo "ERROR: Tesseract does not list '$language' in $TESSDATA" >&2
    exit 5
  fi
done
echo "OCR is ready. Languages in $TESSDATA: $*"
echo "Try it: python scripts/read_pdf.py <scanned.pdf> --ocr"
