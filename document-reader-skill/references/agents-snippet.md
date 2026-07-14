# Project Agent Instruction Snippets

Use the native project instruction file for each coding agent:

| Agent | User skill directory | Project instruction template |
|---|---|---|
| Codex | `~/.agents/skills/document-reader` | `templates/AGENTS.document-reader.md` → `AGENTS.md` |
| Claude Code | `~/.claude/skills/document-reader` | `templates/CLAUDE.document-reader.md` → `CLAUDE.md` |
| Gemini CLI | `~/.gemini/skills/document-reader` | `templates/GEMINI.document-reader.md` → `GEMINI.md` |

The setup scripts install these automatically. Append a template manually only
when the corresponding project instruction file is managed outside the setup
workflow. Keep the marker `## Local requirements (document-reader)` so repeated
installation remains idempotent.

