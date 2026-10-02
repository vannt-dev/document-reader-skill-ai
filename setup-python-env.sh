#!/bin/sh
set -eu

PYTHON_VERSION=${1:-3.12}
RUNTIME_ROOT=${DOCUMENT_READER_HOME:-"$HOME/.document-reader"}
BIN_DIR="$RUNTIME_ROOT/bin"
VENV_PATH=${2:-"$RUNTIME_ROOT/venv"}
UV="$BIN_DIR/uv"

mkdir -p "$BIN_DIR"

if [ ! -x "$UV" ]; then
  echo "Installing uv from the official Astral installer..."
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$BIN_DIR" UV_NO_MODIFY_PATH=1 sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$BIN_DIR" UV_NO_MODIFY_PATH=1 sh
  else
    echo "ERROR: curl or wget is required to install uv." >&2
    exit 2
  fi
fi

if [ ! -x "$UV" ]; then
  echo "ERROR: uv installation failed: $UV was not created" >&2
  exit 3
fi

echo "Installing managed Python $PYTHON_VERSION..."
"$UV" python install "$PYTHON_VERSION"

echo "Creating virtual environment at $VENV_PATH..."
"$UV" venv --python "$PYTHON_VERSION" "$VENV_PATH"

PYTHON="$VENV_PATH/bin/python"
echo "Installing document-reader dependencies..."
"$UV" pip install --python "$PYTHON" openpyxl pypdf pdfplumber

"$PYTHON" -c "import openpyxl, pypdf, sys; print(sys.version); print('openpyxl', openpyxl.__version__); print('pypdf', pypdf.__version__)"
echo "Document Reader Python environment is ready: $PYTHON"
