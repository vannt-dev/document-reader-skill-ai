#!/usr/bin/env python3
"""Query the pre-parsed document cache without re-reading source files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import add_output_argument, emit


def _read_json(path: Path):
    """Return (data, corrupt).

    data is the parsed JSON, or None when the file is absent. corrupt is True
    when the file exists but cannot be read as JSON, so callers can degrade
    gracefully instead of aborting the whole query.
    """
    if not path.is_file():
        return None, False
    try:
        return json.loads(path.read_text(encoding="utf-8")), False
    except (json.JSONDecodeError, OSError):
        return None, True


def _manifest_hashes(cache_dir: Path) -> dict[str, str]:
    manifest, _ = _read_json(cache_dir / "manifest.json")
    if not manifest:
        return {}
    return {doc["path"]: doc.get("sha256", "") for doc in manifest.get("documents", [])}


def query(cache_dir, keyword=None, doc=None, block_id=None, label=None, max_results=50) -> dict:
    cache_dir = Path(cache_dir)
    warnings: list[str] = []
    index, index_corrupt = _read_json(cache_dir / "index.json")
    if index_corrupt:
        warnings.append("index.json is unreadable; rebuild with build_cache.py.")
        return _envelope(keyword, doc, block_id, label, [], False, warnings)
    if index is None:
        warnings.append("No index.json found; run build_cache.py first.")
        return _envelope(keyword, doc, block_id, label, [], False, warnings)

    manifest_hashes = _manifest_hashes(cache_dir)
    needle = keyword.casefold() if keyword else None
    label_needle = label.casefold() if label else None
    results: list[dict] = []
    truncated = False

    for document in index.get("documents", []):
        if doc and document["doc_id"] != doc:
            continue
        current = manifest_hashes.get(document["path"])
        stale = current is not None and current != document.get("sha256")
        cache_payload, cache_corrupt = _read_json(cache_dir / "cache" / f"{document['doc_id']}.json")
        if cache_corrupt or cache_payload is None:
            warnings.append(f"cache for {document['doc_id']} is unreadable; rebuild with build_cache.py.")
            continue
        blocks = cache_payload.get("blocks", [])
        for block in blocks:
            if block_id and block["block_id"] != block_id:
                continue
            if label_needle and label_needle not in block["label"].casefold():
                continue
            if needle:
                haystack = (block["label"] + json.dumps(block["content"], ensure_ascii=False)).casefold()
                if needle not in haystack:
                    continue
            if len(results) >= max_results:
                truncated = True
                break
            result = {
                "doc_id": document["doc_id"],
                "path": document["path"],
                "block_id": block["block_id"],
                "ref": block["ref"],
                "label": block["label"],
                "stale": stale,
            }
            if stale:
                warnings.append(f"{document['doc_id']} is stale; rebuild with build_cache.py.")
            else:
                result["content"] = block["content"]
            results.append(result)
        if truncated:
            break

    return _envelope(keyword, doc, block_id, label, results, truncated, warnings)


def _envelope(keyword, doc, block_id, label, results, truncated, warnings) -> dict:
    return {
        "schema_version": "1.0",
        "query": {"keyword": keyword, "doc": doc, "block_id": block_id, "label": label},
        "results": results,
        "truncated": truncated,
        "warnings": sorted(set(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("keyword", nargs="?", help="Case-insensitive keyword over label and content")
    parser.add_argument("--cache-dir", default=".document-reader")
    parser.add_argument("--doc", help="Restrict to a doc_id")
    parser.add_argument("--block-id", help="Return exactly this block")
    parser.add_argument("--label", help="Case-insensitive label substring")
    parser.add_argument("--max-results", type=int, default=50)
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        if args.max_results < 1:
            raise ValueError("max-results must be positive")
        result = query(
            args.cache_dir, args.keyword, args.doc, args.block_id, args.label, args.max_results
        )
        emit(result, args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
