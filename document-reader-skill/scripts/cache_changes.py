"""What changed between two cached versions of a document. Pure; no openpyxl.

A document's cache blocks are cut into comparable units, each with a key that
survives edits elsewhere in the document:

- a section, page or slide, keyed by its heading path ("Auth > Tokens") or label;
- a requirement defined in text, keyed by its ID (a line that starts with
  REQ-12, FR-3.1, US-7 ...), running to the next blank line, heading or ID;
- a table row (Excel, CSV, PDF table), keyed by its requirement ID cell when it
  has one, else by its first cell, else by its row number;
- a table header.

Units present only in the new version are added, only in the old one removed,
and in both with different content changed. Keys used twice get "#2", "#3".
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re

DEFAULT_ID_PATTERN = r"[A-Z][A-Z0-9]*(?:[-_][A-Z][A-Z0-9]*)*[-_]\d+(?:\.\d+)*"
# What may sit in front of an ID on the line that defines it: list markers,
# heading hashes, table pipes, quote marks, bold or a bracket.
LEADER = re.compile(r"^(?:\[[ xX]\]\s|[\s>#|*_\[(+-]|\d+[.)]\s)*")
HEADING_LINE = re.compile(r"^#{1,6}\s")
SEPARATOR = " > "
MAX_DIFF_LINES = 40
MAX_EXCERPT_CHARS = 600
# A change report keeps at most this many entries; the counts stay exact.
MAX_ENTRIES = 1000


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _unique(key: str, seen: dict[str, int]) -> str:
    seen[key] = seen.get(key, 0) + 1
    return key if seen[key] == 1 else f"{key}#{seen[key]}"


def _defined_id(line: str, pattern: re.Pattern) -> str | None:
    rest = line[LEADER.match(line).end():]
    match = pattern.match(rest)
    if not match or rest[match.end():match.end() + 1].isalnum():
        return None
    return match.group(0)


def _requirements(text: str, pattern: re.Pattern) -> list[tuple[str, int, str]]:
    """(id, 1-based line in the block, text) for each requirement defined in a block."""
    lines = text.splitlines()
    found = []
    number = 0
    while number < len(lines):
        line = lines[number]
        requirement = _defined_id(line, pattern)
        if not requirement:
            number += 1
            continue
        heading = bool(HEADING_LINE.match(line))
        end = number + 1
        # A table row is one line; a heading runs to the next heading; any
        # other line runs to a blank line, a heading or the next requirement.
        if " | " not in line or heading:
            while end < len(lines):
                following = lines[end]
                if HEADING_LINE.match(following):
                    break
                if not heading and (not following.strip() or _defined_id(following, pattern)):
                    break
                end += 1
        found.append((requirement, number + 1, "\n".join(lines[number:end]).rstrip()))
        number = end if not heading else number + 1
    return found


def units(blocks: list[dict], id_pattern: str | None = None) -> dict[str, dict]:
    """Comparable units of a document's blocks, keyed, in document order."""
    pattern = re.compile(id_pattern or DEFAULT_ID_PATTERN)
    result: dict[str, dict] = {}
    seen: dict[str, int] = {}
    path: list[tuple[int, str]] = []
    headers_seen: set[str] = set()

    def add(key: str, unit: dict) -> None:
        result[_unique(key, seen)] = unit

    for block in blocks:
        content, ref = block.get("content", {}), block.get("ref", {})
        if "rows" in content:
            scope = ref.get("sheet") or (block["label"] if "table" in ref else "")
            prefix = f"{scope}{SEPARATOR}" if scope else ""
            named = f"{scope} " if scope else ""
            headers = content.get("headers", [])
            if scope not in headers_seen:
                headers_seen.add(scope)
                add(f"{prefix}(header)", {
                    "kind": "header", "label": f"{named}header", "block_id": block["block_id"],
                    "ref": ref, "cells": headers, "hash": _digest(headers),
                })
            for row in content.get("rows", []):
                cells = row.get("cells", [])
                values = [str(cell).strip() if cell is not None else "" for cell in cells]
                requirement = next((value for value in values if pattern.fullmatch(value)), None)
                first = values[0][:80] if values else ""
                key = requirement or first or f"row {row['row']}"
                label = f"{named}row {row['row']}" + (f": {requirement or first}" if key != f"row {row['row']}" else "")
                unit = {
                    "kind": "row", "label": label, "block_id": block["block_id"],
                    "ref": {**{name: ref[name] for name in ("sheet", "page", "table") if name in ref}, "row": row["row"]},
                    "cells": cells, "hash": _digest(cells),
                }
                if requirement:
                    unit["requirement_id"] = requirement
                add(f"{prefix}{key}", unit)
            continue

        text = content.get("text", "")
        heading, level = ref.get("heading"), ref.get("level") or 0
        if heading:
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, heading))
            key = SEPARATOR.join(title for _, title in path)
        else:
            key = block["label"]
        add(key, {
            "kind": "section", "label": block["label"], "block_id": block["block_id"], "ref": ref,
            "text": text, "hash": _digest(_normalize(text)),
        })
        for requirement, line, body in _requirements(text, pattern):
            add(requirement, {
                "kind": "requirement", "requirement_id": requirement,
                "label": body.splitlines()[0].strip()[:120], "block_id": block["block_id"],
                "ref": ref, "block_line": line, "text": body, "hash": _digest(_normalize(body)),
            })
    return result


def _diff(before: str, after: str) -> tuple[list[str], bool]:
    lines = []
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=1):
        if line.startswith(("---", "+++")):
            continue
        lines.append("..." if line.startswith("@@") else line)
    if lines and lines[0] == "...":
        lines = lines[1:]
    return lines[:MAX_DIFF_LINES], len(lines) > MAX_DIFF_LINES


def _excerpt(unit: dict) -> dict:
    if "cells" in unit:
        return {"cells": unit["cells"]}
    text = unit.get("text", "")
    return {"text": text[:MAX_EXCERPT_CHARS], "text_truncated": len(text) > MAX_EXCERPT_CHARS}


def _entry(key: str, unit: dict) -> dict:
    entry = {"key": key, "kind": unit["kind"], "label": unit["label"]}
    if "requirement_id" in unit:
        entry["requirement_id"] = unit["requirement_id"]
    entry["block_id"] = unit["block_id"]
    entry["ref"] = unit["ref"]
    if "block_line" in unit:
        entry["block_line"] = unit["block_line"]
    return entry


def compare(old_blocks: list[dict], new_blocks: list[dict], id_pattern: str | None = None) -> dict:
    """Added, changed and removed units from the old blocks to the new ones.

    Added and changed entries point at the new version (`block_id`, `ref`);
    removed entries at the old one, with what the unit held. A changed text
    unit carries a short line diff, a changed row its cells before and after.
    """
    old, new = units(old_blocks, id_pattern), units(new_blocks, id_pattern)
    added, changed, removed = [], [], []
    unchanged = 0
    for key, unit in new.items():
        previous = old.get(key)
        if previous is None:
            entry = _entry(key, unit)
            if unit["kind"] != "section":  # a whole section is fetched by its block_id
                entry["after"] = _excerpt(unit)
            added.append(entry)
        elif previous["hash"] != unit["hash"]:
            entry = _entry(key, unit)
            if "cells" in unit:
                entry["before"], entry["after"] = {"cells": previous["cells"]}, {"cells": unit["cells"]}
            else:
                entry["diff"], truncated = _diff(previous["text"], unit["text"])
                if truncated:
                    entry["diff_truncated"] = True
            changed.append(entry)
        else:
            unchanged += 1
    for key, unit in old.items():
        if key not in new:
            entry = _entry(key, unit)
            entry["before"] = _excerpt(unit)
            removed.append(entry)

    report = {
        "summary": {"added": len(added), "changed": len(changed), "removed": len(removed), "unchanged": unchanged},
        "added": added, "changed": changed, "removed": removed,
    }
    if len(added) + len(changed) + len(removed) > MAX_ENTRIES:
        budget = MAX_ENTRIES
        for name in ("changed", "added", "removed"):
            report[name] = report[name][:budget]
            budget -= len(report[name])
        report["truncated"] = True
    return report
