# Project Update Workflow

Use this workflow when a coding agent must read requirements from a local folder and update the current project.

## Inputs

- Project boundary: current working directory unless explicitly overridden.
- Requirements boundary: the folder or files named by the user, for example `./requirements`.
- Change objective: feature, bug fix, migration, or named requirement subset.

## Procedure

1. Discover repository instructions and project structure.
2. Load `.document-reader/knowledge.md` when present.
3. Run `index_documents.py` and write `.document-reader/manifest.json`.
4. Compare source hashes; invalidate stale knowledge before reuse.
5. Inspect outlines, sheets, dimensions, and small previews inside the authorized boundary.
6. Search for terms from the change objective, or discover actionable requirements when only a folder was supplied.
7. Extract bounded sections or ranges with source references.
8. Create an internal mapping:

   | Requirement source | Requirement | Current code | Planned change | Validation |
   |---|---|---|---|---|
   | Sheet/cells or heading/lines | Expected behavior | Relevant files/symbols | Files to edit | Tests/checks |

9. Inspect mapped code and existing tests.
10. Apply the smallest coherent implementation that satisfies the evidence.
11. Update tests and documentation when required by the change.
12. Run relevant checks, expanding validation when the change has broad impact.
13. Update `.document-reader/knowledge.md` with verified sources, mappings, status, decisions, and validation.
14. Report:
    - requirement sources implemented;
    - files changed;
    - tests/checks run and results;
    - requirements not implemented and why;
    - ambiguities or assumptions.

## Responsibility boundary

- Reader scripts: inspect, search, extract, and normalize documents.
- Host coding agent: reason across requirements and repository, edit files, and run tests.
- Provider adapters: optionally return model analysis; they have no filesystem or command tools.

Never interpret a successful `run_ai.py` response as a successful project update.

## Cross-context continuity

The model conversation is disposable. Treat `.document-reader/manifest.json` and
`.document-reader/knowledge.md` as the durable handoff. At the beginning of every
new context, load them, refresh the manifest, and re-read only changed or newly
relevant sources.
