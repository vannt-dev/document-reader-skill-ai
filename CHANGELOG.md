# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.4.1] - 2026-10-31

Fixes the anchor of a Word comment on words replaced with tracking on.

### Fixed

- A Word comment on words that were then replaced with tracking on had an empty `anchor`:
  Word leaves only the deleted words inside the comment. It now gives those words, with
  `anchor_deleted: true`. ([#23](https://github.com/vannt-dev/document-reader-skill-ai/pull/23))

## [1.4.0] - 2026-10-31

Reads Word comments and tracked changes: `read_docx.py` and the cache give each section's
comments and changes, and `--show-changes` marks the changes in the text.

### Added

- Word comments and tracked changes. `read_docx.py` and the cache now give a section's
  `comments` (author, date, text, the anchored words, replies, resolved) and `revisions`
  (inserted, deleted, moved text with author and date), each with its paragraph number.
  `read_docx.py --show-changes`, and `tracked_text` in the cache, write the changes into the
  text as `{++inserted++}` and `{--deleted--}`; the outline counts both. A document without
  comments or tracked changes reads exactly as before, so its cache does not change. To add
  them to a cache built earlier, run `build_cache.py --force`.
  ([#21](https://github.com/vannt-dev/document-reader-skill-ai/pull/21))

### Changed

- Word text left behind by a tracked move or deletion is no longer read: a move stored as
  ordinary text at its old place, and tabs or line breaks inside deleted text. The next
  cache build of such a document reports the section as changed.
  ([#21](https://github.com/vannt-dev/document-reader-skill-ai/pull/21))
- Cache searches skip a Word comment's or change's date and paragraph number.
  ([#21](https://github.com/vannt-dev/document-reader-skill-ai/pull/21))

## [1.3.0] - 2026-10-29

Ranks cache searches: multi-word queries now match all words anywhere and are ranked;
`--order doc` keeps document order.

### Added

- `query_cache.py --limit N`, another name for `--max-results N`; both now keep the N best
  matches rather than the first N found.
  ([#17](https://github.com/vannt-dev/document-reader-skill-ai/pull/17))
- `query_cache.py --explain` adds each result's `score`: how many of the words it holds,
  whether it holds the whole phrase, and its weight.
  ([#17](https://github.com/vannt-dev/document-reader-skill-ai/pull/17))

### Changed

- `query_cache.py` ranks keyword searches. A keyword of several words now finds the blocks
  holding every word, in any order and in any of the block's values, not only the words
  together as typed; the best come first: blocks with more of the words, then those with
  the whole phrase, then those where the words are rarer or repeated, then document order.
  `--order doc` keeps the old order, `--match phrase` the old matching, and `--match any`
  finds blocks with any of the words. Each word keeps the accent rule of 1.2.0.
  ([#17](https://github.com/vannt-dev/document-reader-skill-ai/pull/17))

## [1.2.0] - 2026-10-28

Finds Vietnamese typed without accents, and fixes searches that matched every block.

### Added

- Searching ignores accents when the query is typed without them: `search_document.py`,
  `query_cache.py --keyword` and `--label` with `dang nhap` find "Đăng nhập". A query typed
  with accents still matches them as written; `--regex` and `--case-sensitive` are unchanged.
  ([#14](https://github.com/vannt-dev/document-reader-skill-ai/pull/14))

### Fixed

- `query_cache.py --keyword` searched the cached block as JSON, so a word like
  `text`, `rows` or `cells` matched every block, and a phrase with a quote or a
  line break never matched. It now searches only the block's label and the text
  and cell values it holds.
  ([#13](https://github.com/vannt-dev/document-reader-skill-ai/pull/13))
- On Windows, a script whose output held Vietnamese (or any text outside the console's code
  page) failed with exit code 2 when its output went to a pipe. Output is now always UTF-8.
  ([#14](https://github.com/vannt-dev/document-reader-skill-ai/pull/14))

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

[Unreleased]: https://github.com/vannt-dev/document-reader-skill-ai/compare/v1.4.1...HEAD
[1.4.1]: https://github.com/vannt-dev/document-reader-skill-ai/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/vannt-dev/document-reader-skill-ai/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/vannt-dev/document-reader-skill-ai/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/vannt-dev/document-reader-skill-ai/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/vannt-dev/document-reader-skill-ai/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/vannt-dev/document-reader-skill-ai/releases/tag/v1.0.0
