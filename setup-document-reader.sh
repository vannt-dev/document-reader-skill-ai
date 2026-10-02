#!/bin/sh
set -eu

SCRIPT_ROOT=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
SKILL_SOURCE="$SCRIPT_ROOT/document-reader-skill"
RUNTIME_ROOT=${DOCUMENT_READER_HOME:-"$HOME/.document-reader"}
VENV_PYTHON="$RUNTIME_ROOT/venv/bin/python"

PROJECT_INPUT=${1:-"$PWD"}
REQUIREMENTS_INPUT=${2:-requirements}
AGENT=${3:-all}
INSTALL_DEPS=${4:-}

case "$AGENT" in
  --agent) AGENT=${4:-all}; INSTALL_DEPS=${5:-} ;;
  --agent=*) AGENT=${AGENT#--agent=} ;;
  --install-deps|/install-deps) INSTALL_DEPS=$AGENT; AGENT=all ;;
esac
case "$AGENT" in codex|claude|gemini|all) ;; *) echo "ERROR: agent must be codex, claude, gemini, or all" >&2; exit 2 ;; esac

[ -f "$SKILL_SOURCE/SKILL.md" ] || { echo "ERROR: Skill source not found: $SKILL_SOURCE" >&2; exit 2; }
[ -d "$PROJECT_INPUT" ] || { echo "ERROR: Project folder not found: $PROJECT_INPUT" >&2; exit 2; }

PROJECT_ROOT=$(CDPATH= cd -P "$PROJECT_INPUT" && pwd)
case "$REQUIREMENTS_INPUT" in /*) REQUIREMENTS_ROOT=$REQUIREMENTS_INPUT ;; *) REQUIREMENTS_ROOT="$PROJECT_ROOT/$REQUIREMENTS_INPUT" ;; esac

install_skill() {
  target=$1
  echo "Installing skill to $target..."
  mkdir -p "$target"
  cp -R "$SKILL_SOURCE"/. "$target"/
}

append_instructions() {
  file=$1
  template=$2
  touch "$file"
  if grep -Fq "## Local requirements (document-reader)" "$file"; then
    echo "Preserved document-reader instructions in $(basename "$file")"
  else
    printf '\n' >> "$file"
    cat "$template" >> "$file"
    echo "Added document-reader instructions to $(basename "$file")"
  fi
}

echo "[1/6] Installing agent skills..."
if [ "$AGENT" = codex ] || [ "$AGENT" = all ]; then install_skill "$HOME/.agents/skills/document-reader"; fi
if [ "$AGENT" = claude ] || [ "$AGENT" = all ]; then install_skill "$HOME/.claude/skills/document-reader"; fi
if [ "$AGENT" = gemini ] || [ "$AGENT" = all ]; then install_skill "$HOME/.gemini/skills/document-reader"; fi

echo "[2/6] Creating project state..."
mkdir -p "$REQUIREMENTS_ROOT" "$PROJECT_ROOT/.document-reader"
if [ ! -f "$PROJECT_ROOT/.document-reader/knowledge.md" ]; then
  cp "$SKILL_SOURCE/references/project-memory-template.md" "$PROJECT_ROOT/.document-reader/knowledge.md"
  echo "Created .document-reader/knowledge.md"
else
  echo "Preserved existing .document-reader/knowledge.md"
fi

echo "[3/6] Configuring agent instructions..."
if [ "$AGENT" = codex ] || [ "$AGENT" = all ]; then append_instructions "$PROJECT_ROOT/AGENTS.md" "$SKILL_SOURCE/templates/AGENTS.document-reader.md"; fi
if [ "$AGENT" = claude ] || [ "$AGENT" = all ]; then append_instructions "$PROJECT_ROOT/CLAUDE.md" "$SKILL_SOURCE/templates/CLAUDE.document-reader.md"; fi
if [ "$AGENT" = gemini ] || [ "$AGENT" = all ]; then append_instructions "$PROJECT_ROOT/GEMINI.md" "$SKILL_SOURCE/templates/GEMINI.document-reader.md"; fi

echo "[4/6] Checking Python..."
PYTHON=""
if [ -x "$VENV_PYTHON" ]; then PYTHON=$VENV_PYTHON
elif command -v python3 >/dev/null 2>&1; then PYTHON=python3
elif command -v python >/dev/null 2>&1; then PYTHON=python
fi
if [ -z "$PYTHON" ] || ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
  echo "WARNING: Python 3.10+ was not found; indexing was skipped."
  echo "Run: sh \"$SCRIPT_ROOT/setup-python-env.sh\"; then run this installer again."
  exit 0
fi

echo "[5/6] Checking optional dependencies..."
if [ "$INSTALL_DEPS" = "--install-deps" ] || [ "$INSTALL_DEPS" = "/install-deps" ]; then "$PYTHON" -m pip install openpyxl pypdf; fi

echo "[6/6] Indexing requirements..."
"$PYTHON" "$SKILL_SOURCE/scripts/index_documents.py" "$REQUIREMENTS_ROOT" --output "$PROJECT_ROOT/.document-reader/manifest.json" || {
  echo "ERROR: Indexing failed. Install openpyxl and pypdf with --install-deps when Excel or PDF files are present." >&2; exit 4;
}

echo "Document Reader deployment completed for agent: $AGENT"
echo "Project: $PROJECT_ROOT"
echo "Requirements: $REQUIREMENTS_ROOT"
