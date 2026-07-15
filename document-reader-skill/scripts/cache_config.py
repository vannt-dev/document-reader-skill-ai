"""Share-scope config and .gitignore management for the document cache."""

from __future__ import annotations

import json
from pathlib import Path

SHARE_LOCAL = "local"
SHARE_COMMIT = "commit"
VALID_SHARE = {SHARE_LOCAL, SHARE_COMMIT}

GITIGNORE_MARK = "# document-reader cache (share=local)"
IGNORE_LINES = [
    ".document-reader/cache/",
    ".document-reader/index.json",
    ".document-reader/manifest.json",
]


def write_config(cache_dir: Path, share: str) -> None:
    if share not in VALID_SHARE:
        raise ValueError(f"Unknown share scope {share!r}; use 'local' or 'commit'")
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "config.json").write_text(
        json.dumps({"share": share}, indent=2) + "\n", encoding="utf-8"
    )


def apply_gitignore(project_dir: Path, share: str) -> None:
    if share not in VALID_SHARE:
        raise ValueError(f"Unknown share scope {share!r}; use 'local' or 'commit'")
    gitignore = Path(project_dir) / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.is_file() else []
    has_mark = GITIGNORE_MARK in lines

    if share == SHARE_LOCAL:
        if has_mark:
            return
        block = [GITIGNORE_MARK, *IGNORE_LINES]
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(block)
    else:  # commit: strip our managed block
        managed = {GITIGNORE_MARK, *IGNORE_LINES}
        lines = [line for line in lines if line not in managed]

    if lines:
        gitignore.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif gitignore.is_file():
        gitignore.write_text("", encoding="utf-8")
