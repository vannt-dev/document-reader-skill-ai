## Local requirements (document-reader)

Activate the `document-reader` Agent Skill when the user provides a local requirements folder.

1. Treat the supplied folder as the requirements boundary and this repository as the project boundary.
2. Load `.document-reader/knowledge.md` if it exists.
3. Refresh `.document-reader/manifest.json` with the skill's `index_documents.py`.
4. Invalidate knowledge whose source hash changed.
5. Read only relevant sections or spreadsheet ranges.
6. Map requirements to code, update source and tests, and run validation.
7. Update `.document-reader/knowledge.md` for future contexts.
8. Never send project data to an external provider without explicit authorization.

