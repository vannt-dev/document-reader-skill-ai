# Document Reader Skill

[![CI](https://github.com/vannt-dev/document-reader-skill-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/vannt-dev/document-reader-skill-ai/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Tiếng Việt: [README.vi.md](README.vi.md)

A skill for coding agents that reads requirement documents from a local folder,
selectively, and then updates the source code and tests of the current project.

Once it is installed, a folder name is enough:

```text
Apply requirements from ./requirements
```

```text
Local requirements
        ↓
Document Reader scripts (inspect/search/extract)
        ↓
Relevant evidence with source references
        ↓
Host coding agent (Codex, Claude Code, Gemini CLI, ...)
        ↓
Project code changes + tests
```

The coding agent is what changes the project. The skill's scripts only read and
normalize documents. The OpenAI, Anthropic and Gemini adapters are optional, for
analysis through an API, and cannot touch the file system.

## Supported documents

| Format | Extensions | Cited by |
|---|---|---|
| Excel | `.xlsx`, `.xlsm` | sheet and cell |
| CSV | `.csv`, `.tsv` | cell |
| Markdown | `.md`, `.markdown` | heading and line |
| PDF | `.pdf`, with tables, and scanned pages through OCR | page |
| Word | `.docx` | heading and paragraph |
| PowerPoint | `.pptx` | slide |
| HTML | `.html`, `.htm`, such as Confluence or wiki exports | heading and paragraph |
| Plain text | `.txt` | line |

Legacy `.xls`, `.doc` and `.ppt` files must be saved in the newer format first.
Pictures (`.png`, `.jpg`, ...) can be read one at a time with OCR but are not indexed.

## Knowledge kept between sessions

What the agent learns is stored in the project, so a later session, or another
agent, picks it up:

```text
.document-reader/
├── manifest.json   # hashes and structure of the documents
├── index.json      # catalog of the cached blocks of each document
├── cache/          # full normalized content, one JSON file per document
└── knowledge.md    # requirements, code mapping, status and validation
```

This is context persisted in the project, not hidden model memory, so Codex,
Claude Code or Gemini CLI can all read it when they are set up to use the skill.

Documents are read once. When one is edited, only that document is read again,
and the cache records what was added, changed and removed, by requirement ID
(`REQ-12`), heading or table row, so the agent applies only what changed:
`query_cache.py --changes --doc <doc-id>`.

## Python environment

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-python-env.ps1
```

Linux/macOS:

```bash
sh setup-python-env.sh
```

Both scripts use `uv` to install Python 3.12, create a separate virtual
environment in `~/.document-reader/venv`, and install `openpyxl`, `pypdf` and
`pdfplumber`.

### OCR for scanned PDFs and pictures (optional)

Scanned PDF pages and photos have no text layer. To read them with Tesseract:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-ocr.ps1
```

```bash
sh setup-ocr.sh
```

On Windows the script installs Tesseract with `winget` when it is missing (Windows
asks for permission); on Linux and macOS install `tesseract` with your package
manager first. Both scripts download the Vietnamese and English language data into
`~/.document-reader/tessdata`. Everything else works without this step; scanned
pages are then reported as unread.

## Install for a project

Windows:

```powershell
.\setup-document-reader.bat C:\Git\my-project requirements --agent all /install-deps
```

Linux/macOS:

```bash
chmod +x setup-document-reader.sh
./setup-document-reader.sh /path/to/my-project requirements --agent all --install-deps
```

The script installs the skill for Codex, Claude Code and Gemini CLI, and creates
`requirements/`, `.document-reader/`, each agent's instruction file and the first
manifest. Run it again after updating this repository so installed copies pick
up the change.

## Documentation

- [`document-reader-skill/SKILL.md`](document-reader-skill/SKILL.md): the workflow the agent follows.
- [`document-reader-skill/README.md`](document-reader-skill/README.md) and [`USAGE.md`](USAGE.md): installation, commands and troubleshooting (in Vietnamese).
- [`CHANGELOG.md`](CHANGELOG.md): changes by release.

## License

Released under the MIT license. See [LICENSE](LICENSE).
