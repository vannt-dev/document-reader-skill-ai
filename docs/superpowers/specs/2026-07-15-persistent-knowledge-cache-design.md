# Design: Persistent Knowledge Cache for Document Reader

Date: 2026-07-15
Status: Approved

## Problem

The `document-reader` skill reads Excel/Markdown requirement (SRS) documents so a
coding agent can implement and reason about them. Today it persists only two
artifacts:

- `manifest.json` — deterministic metadata (paths, SHA-256, mtime, structure). No
  content.
- `knowledge.md` — a deliberately distilled summary (confirmed requirements +
  code mappings). Its template states "Do not copy full documents into it."

Consequence: the **actual extracted requirement content is not persisted**. When a
new context needs a detail not captured in the distilled summary, it must re-run
the reader scripts and **re-parse the source documents**. This wastes time and
tokens every time the context window is exhausted — the exact cost the user wants
to eliminate.

## Goal

Read each document **once**, persist the full normalized content durably, and let
any later context (Q&A/lookup or code implementation, any host agent) retrieve
only the relevant slice **without re-parsing the source files**.

## Decisions (confirmed with user)

1. **Two-layer storage** — a full normalized content cache *plus* the existing
   distilled `knowledge.md` summary.
2. **Purpose-neutral storage** — the cache must serve both requirement lookup/Q&A
   and code implementation, so it stores content independent of any single task.
3. **Small index + on-demand query** — always load a small index/summary; fetch
   detail by querying the pre-parsed cache, never by re-parsing Excel/MD, and
   never by loading the whole cache into context.
4. **User-configurable sharing scope** — default local (gitignored); opt-in to
   commit for team + cross-agent sharing.

## Chosen approach: Approach A

Normalized JSON content cache + a lightweight local query script. This matches the
existing architecture (JSON artifacts, Python stdlib + `openpyxl`, deterministic
single-purpose scripts) and adds no heavy dependencies. Rejected alternatives:

- **B — one big knowledge file**: querying means reading a large file, recreating
  the token problem for large SRS. Contradicts decision 3.
- **C — SQLite FTS / vector store**: strongest retrieval but adds a DB/embedding
  dependency, hurts cross-agent portability, and is overkill now. Kept as a
  possible future upgrade path from A.

## Storage model

Directory layout under the project:

```text
.document-reader/
├── manifest.json          # existing: path, SHA-256, mtime, structure
├── index.json             # NEW: small catalog, always loaded
├── cache/                 # NEW: full normalized content (read-once)
│   ├── business-md.json
│   └── api-xlsx.json
├── knowledge.md           # existing: distilled requirements + code mapping
└── config.json            # NEW: configuration (e.g. share = local | commit)
```

### `cache/<doc-id>.json` — full content, split into blocks

```jsonc
{
  "doc_id": "api-xlsx",
  "path": "requirements/api.xlsx",
  "sha256": "…",            // to detect stale content
  "type": "excel",
  "blocks": [
    {
      "block_id": "api!A1:H12",
      "ref": { "sheet": "API", "range": "A1:H12" },
      "label": "Authentication endpoints",   // heading / column labels for the index
      "content": { "headers": ["…"], "rows": [["…"]] }
    }
  ]
}
```

Block granularity (explicit, to avoid ambiguity):

- **Excel**: one block **per sheet** by default, holding that sheet's `headers`
  and all `rows`. If a sheet exceeds a configurable window (default 500 rows), it
  is split into contiguous row-range blocks (`A1:H500`, `A501:H1000`, …) so no
  single block is unbounded. `block_id` = `"<sheet>!<range>"`.
- **Markdown**: one block **per heading section** (heading text plus its body up
  to the next heading of equal or higher level). `ref` carries `heading` and
  `lines`; `block_id` = `"<slug-of-heading>@L<start>-<end>"`.
- Every block is **self-traceable** (`ref` + document `sha256`), preserving the
  skill's source-traceability guarantee.

### `index.json` — small catalog (always loaded)

```jsonc
{
  "documents": [
    {
      "doc_id": "api-xlsx",
      "path": "requirements/api.xlsx",
      "sha256": "…",
      "blocks": [
        { "block_id": "api!A1:H12", "label": "Authentication endpoints" }
      ]
    }
  ]
}
```

The agent reads the index to learn **what exists and where** without loading any
`content`. Detail is pulled from the cache only on demand.

**Key property:** `cache/` holds the entire parsed content from a single read;
later contexts **never reopen the Excel/MD source** — they read JSON or query it.

## Components and data flow

| Script | State | Responsibility |
|---|---|---|
| `build_cache.py` | NEW | Read `manifest.json`; for each document, reuse the existing reader logic to extract the **full** content as blocks; write `cache/<doc-id>.json` and update `index.json`. Rebuild only documents whose hash changed. |
| `query_cache.py` | NEW | Query the pre-parsed `cache/`: filter by keyword / `--doc` / `--block-id` / `--label`; return matching blocks with refs. **Never opens Excel/MD.** |
| `index_documents.py` | keep | Still produces `manifest.json` (metadata + hash); input to `build_cache.py`. |
| `read_excel.py`, `read_markdown.py`, `inspect_excel.py` | keep, reused | `build_cache.py` calls their parse logic so extraction is not duplicated. |
| `search_document.py` | keep | Search of raw source when cache is absent; once cache exists, `query_cache.py` is the fast path. |

### First run (any context)

```text
requirements/  →  index_documents.py  →  manifest.json
manifest.json  →  build_cache.py      →  cache/*.json + index.json
(agent distills)                       →  knowledge.md
```

### Later contexts (read-once pays off)

```text
1. Load index.json + knowledge.md (small).
2. index_documents.py → compare hashes. Changed docs → build_cache.py rebuilds
   just those docs.
3. Need detail? → query_cache.py --doc api-xlsx "authentication"
   → returns blocks from JSON, WITHOUT re-parsing Excel.
4. Use for lookup/Q&A OR map to code and edit — depending on the context.
```

### Stale handling

A block/document whose `sha256` differs from the manifest is stale.
`query_cache.py` flags `stale: true` and withholds content until `build_cache.py`
rebuilds it — consistent with the existing "distrust changed hash" principle.

## Configuration and sharing (`config.json`)

```jsonc
{ "share": "local" }   // "local" (default) | "commit"
```

- `local`: setup appends `.document-reader/cache/` and `.document-reader/index.json`
  to `.gitignore` (manifest stays local too). `knowledge.md` is left to the user.
- `commit`: cache/index are **not** gitignored, enabling team + cross-agent
  sharing.
- Set via `build_cache.py --share commit` or a flag in `setup-document-reader`.
  Before switching to `commit`, the script **warns** to check documents for
  secrets.

## SKILL.md integration

- In *"Bootstrap from a folder path"* and *"Persist knowledge across contexts"*:
  add a `build_cache.py` step after indexing to produce the cache + index.
- New context: load `index.json` + `knowledge.md` first; **prefer
  `query_cache.py`** over re-reading source; rebuild only hash-changed docs.
- Add `build_cache.py` and `query_cache.py` to the **Commands** section.
- Add `schemas/document-cache.schema.json` describing `cache/*.json` and
  `index.json`.

## Error handling

- A document that fails to parse (corrupt Excel, legacy `.xls`) is recorded in
  `index.json` with an `error` field and skipped; it does not break the whole
  cache build.
- `query_cache.py` on a missing `doc_id` or an empty cache reports clearly that
  the cache is not built and suggests running `build_cache.py`.
- If a block is cut by a safety limit, keep a `truncated` flag, consistent with
  `normalize_output.py`.

## Testing

- Framework: **pytest** (repo currently has no tests).
- Fixtures: a small `.xlsx` and a small `.md` under `tests/fixtures/`.
- `build_cache.py`: cache/index contain the right blocks, refs, and hashes;
  rebuild touches only hash-changed docs (incremental test).
- `query_cache.py`: filtering by keyword/doc/block returns the right blocks, and
  **does not** invoke `openpyxl` (assert no re-parse, via spy/mock).
- Stale test: change file content → hash changes → query flags `stale`.
- Round-trip: build → query returns the original source content.

## Out of scope

- SQLite FTS / embeddings retrieval (future upgrade from A).
- Automatic secret redaction (only a warning is provided on `commit`).
- Changes to the External API Mode adapters.
