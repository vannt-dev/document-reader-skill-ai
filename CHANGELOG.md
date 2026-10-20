# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.1.0] - 2026-10-21

Reads HTML pages and plain-text files, and reports what changed when a document
is edited.

### Added

- HTML pages (`.html`, `.htm`), such as Confluence or wiki exports, are read as
  text: navigation, scripts, styles and page chrome are dropped; headings,
  paragraphs, lists and tables are kept and cited by paragraph. `read_html.py`
  shows the outline or reads a heading or a paragraph range.
  ([#7](https://github.com/vannt-dev/document-reader-skill-ai/pull/7))
- Plain-text files (`.txt`) are read with their encoding detected (UTF-8, UTF-16
  or Windows-1252) and cited by line. `read_txt.py` shows the outline or reads
  a heading or a line range. CSV files saved as UTF-16 now read too.
  ([#7](https://github.com/vannt-dev/document-reader-skill-ai/pull/7))
- When a document is edited, the cache records what changed since the version
  read before: the requirements (by ID such as `REQ-12`), sections and table
  rows added, changed or removed, with a short diff. `build_cache.py` lists the
  changed documents and `query_cache.py --changes --doc <doc-id>` shows the
  report, so the agent applies only what changed. Caches built by 1.0.0 keep
  working. ([#8](https://github.com/vannt-dev/document-reader-skill-ai/pull/8))
- The skill is licensed under MIT.
  ([#5](https://github.com/vannt-dev/document-reader-skill-ai/pull/5))
- An English README; the Vietnamese one moved to `README.vi.md`.

## [1.0.0] - 2026-10-10

First tagged release of the Document Reader skill.

### Added

- Reads requirement documents from a local folder selectively (inspect, search,
  extract) and hands the host coding agent the relevant evidence with source
  references; project knowledge is kept in `.document-reader/`, with a cache
  that reads a document again only when its hash changes.
- Formats: Excel and Markdown; PDF and Word (`.docx`)
  ([#1](https://github.com/vannt-dev/document-reader-skill-ai/pull/1)); PowerPoint
  (`.pptx`) and CSV ([#2](https://github.com/vannt-dev/document-reader-skill-ai/pull/2));
  tables on PDF pages ([#3](https://github.com/vannt-dev/document-reader-skill-ai/pull/3)).
- OCR for scanned PDF pages and images through Tesseract: `read_pdf.py --ocr`,
  `build_cache.py --ocr` and `read_image.py`; `setup-ocr.ps1` and `setup-ocr.sh`
  install it with the Vietnamese and English data. OCR is optional.
  ([#4](https://github.com/vannt-dev/document-reader-skill-ai/pull/4))
- Setup scripts for Windows, Linux and macOS that install the skill for Codex,
  Claude Code and Gemini CLI.

[Unreleased]: https://github.com/vannt-dev/document-reader-skill-ai/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/vannt-dev/document-reader-skill-ai/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/vannt-dev/document-reader-skill-ai/releases/tag/v1.0.0
