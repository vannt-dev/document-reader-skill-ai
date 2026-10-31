#!/usr/bin/env python3
"""Query the pre-parsed document cache without re-reading source files."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from common import add_output_argument, emit, text_counter, text_matcher


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


UNSEARCHED_KEYS = {"row", "paragraph", "date", "tracked_text"}


def _text_values(content) -> list[str]:
    """The words a block holds: its strings and numbers, not key names or JSON escapes.

    A table row's `row` number is where the row sits, not what it says, so it is left out;
    so are a Word comment's or change's paragraph number and date, and `tracked_text`,
    which repeats the text (the deleted words are in `revisions`).
    """
    if isinstance(content, dict):
        return [
            text for key, value in content.items() if key not in UNSEARCHED_KEYS for text in _text_values(value)
        ]
    if isinstance(content, list):
        return [text for value in content for text in _text_values(value)]
    if isinstance(content, bool) or content is None:
        return []
    return [str(content)]


# How quickly repeating a word stops adding to a block's weight: once is worth
# 1/(1+K) of the most it can add, twice 2/(2+K), and so on (BM25's k1).
SATURATION = 1.2
MATCH_MODES = ("all", "any", "phrase")
ORDERS = ("rank", "doc")


def query(cache_dir, keyword=None, doc=None, block_id=None, label=None, max_results=50,
          match="all", order="rank", explain=False) -> dict:
    """Blocks matching the filters and the keyword.

    A keyword of several words matches a block holding every word (`match="all"`), any of
    them (`"any"`), or the words together as written (`"phrase"`); each word and the phrase
    must sit within one value, never across two cells. With `order="rank"` the blocks holding
    more of the words come first, then those holding the whole phrase, then the heavier ones,
    then document order. A block's weight adds, for each word, how rare the word is among the
    blocks searched (its inverse document frequency) times tf/(tf+K), tf being how often the
    block holds it. `explain=True` adds these numbers to each result as `score`.
    """
    if match not in MATCH_MODES:
        raise ValueError(f"match must be one of {', '.join(MATCH_MODES)}")
    if order not in ORDERS:
        raise ValueError(f"order must be one of {', '.join(ORDERS)}")
    cache_dir = Path(cache_dir)
    warnings: list[str] = []
    echo = (keyword, doc, block_id, label, match, order)
    index, index_corrupt = _read_json(cache_dir / "index.json")
    if index_corrupt:
        warnings.append("index.json is unreadable; rebuild with build_cache.py.")
        return _envelope(*echo, [], False, warnings)
    if index is None:
        warnings.append("No index.json found; run build_cache.py first.")
        return _envelope(*echo, [], False, warnings)

    manifest_hashes = _manifest_hashes(cache_dir)
    label_matches = text_matcher(label) if label else None
    searched: list[tuple[dict, dict, bool]] = []

    for document in index.get("documents", []):
        if doc and document["doc_id"] != doc:
            continue
        current = manifest_hashes.get(document["path"])
        stale = current is not None and current != document.get("sha256")
        cache_payload, cache_corrupt = _read_json(cache_dir / "cache" / f"{document['doc_id']}.json")
        if cache_corrupt or cache_payload is None:
            warnings.append(f"cache for {document['doc_id']} is unreadable; rebuild with build_cache.py.")
            continue
        for block in cache_payload.get("blocks", []):
            if block_id and block["block_id"] != block_id:
                continue
            if label_matches and not label_matches(block["label"]):
                continue
            searched.append((document, block, stale))

    if keyword:
        hits = _rank(keyword, searched, match, order)
    else:
        hits = [(entry, None) for entry in searched]
    truncated = len(hits) > max_results

    results: list[dict] = []
    for (document, block, stale), score in hits[:max_results]:
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
        if explain and score is not None:
            result["score"] = score
        results.append(result)

    return _envelope(*echo, results, truncated, warnings)


def _rank(keyword, searched, match, order):
    """The searched blocks that match the keyword, best first, each with its score."""
    words = list({word.casefold(): word for word in keyword.split()}.values()) or [keyword]
    counters = [text_counter(word) for word in words]
    phrase = text_matcher(keyword)
    counted = []
    for position, entry in enumerate(searched):
        block = entry[1]
        # Each value on its own, so a match never runs from one cell into the next.
        texts = [block["label"], *_text_values(block["content"])]
        counts = [sum(count(text) for text in texts) for count in counters]
        counted.append((position, entry, counts, any(phrase(text) for text in texts)))

    total = len(searched)
    holding = [sum(1 for _, _, counts, _ in counted if counts[i]) for i in range(len(words))]
    rarity = [math.log(1 + (total - n + 0.5) / (n + 0.5)) for n in holding]

    ranked = []
    for position, entry, counts, has_phrase in counted:
        found = sum(1 for tf in counts if tf)
        wanted = {"all": found == len(words), "any": found > 0, "phrase": has_phrase}[match]
        if not wanted:
            continue
        weight = sum(idf * tf / (tf + SATURATION) for idf, tf in zip(rarity, counts))
        score = {"words": found, "phrase": has_phrase, "weight": round(weight, 4)}
        ranked.append(((-found, -has_phrase, -weight, position), entry, score))
    if order == "rank":
        ranked.sort(key=lambda item: item[0])
    return [(entry, score) for _, entry, score in ranked]


def changes(cache_dir, doc=None, max_results=50) -> dict:
    """What changed in each document since the version cached before it.

    With `doc`, that document is always reported, with status "changed",
    "no_previous_version" or "stale". Without it, only documents that have a
    change report, or are stale, are listed. `max_results` bounds the number
    of added, changed and removed entries returned across all documents.
    """
    cache_dir = Path(cache_dir)
    warnings: list[str] = []
    envelope = {"schema_version": "1.0", "query": {"changes": True, "doc": doc}, "documents": [], "truncated": False}
    index, index_corrupt = _read_json(cache_dir / "index.json")
    if index_corrupt or index is None:
        warnings.append(
            "index.json is unreadable; rebuild with build_cache.py." if index_corrupt
            else "No index.json found; run build_cache.py first."
        )
        return {**envelope, "warnings": warnings}

    manifest_hashes = _manifest_hashes(cache_dir)
    budget = max_results
    found = False
    for document in index.get("documents", []):
        if doc and document["doc_id"] != doc:
            continue
        found = True
        entry = {"doc_id": document["doc_id"], "path": document["path"], "sha256": document.get("sha256", "")}
        current = manifest_hashes.get(document["path"])
        if current is not None and current != document.get("sha256"):
            warnings.append(f"{document['doc_id']} is stale; rebuild with build_cache.py, then ask again.")
            envelope["documents"].append({**entry, "status": "stale"})
            continue
        cache_payload, cache_corrupt = _read_json(cache_dir / "cache" / f"{document['doc_id']}.json")
        if cache_corrupt or cache_payload is None:
            warnings.append(f"cache for {document['doc_id']} is unreadable; rebuild with build_cache.py.")
            continue
        report = cache_payload.get("changes")
        if report is None:
            if doc:
                envelope["documents"].append({**entry, "status": "no_previous_version"})
            continue
        entry.update({"status": "changed", "previous_sha256": report.get("previous_sha256", ""),
                      "summary": report.get("summary", {})})
        for name in ("changed", "added", "removed"):
            items = report.get(name, [])
            entry[name] = items[:budget]
            if len(items) > budget:
                envelope["truncated"] = True
            budget = max(budget - len(entry[name]), 0)
        if report.get("truncated"):
            entry["report_truncated"] = True
            warnings.append(
                f"the change report of {document['doc_id']} lists only part of the changes; read the document again."
            )
        envelope["documents"].append(entry)
    if doc and not found:
        warnings.append(f"No document with doc_id {doc!r} in index.json.")
    return {**envelope, "warnings": sorted(set(warnings))}


def _envelope(keyword, doc, block_id, label, match, order, results, truncated, warnings) -> dict:
    return {
        "schema_version": "1.0",
        "query": {"keyword": keyword, "doc": doc, "block_id": block_id, "label": label,
                  "match": match, "order": order},
        "results": results,
        "truncated": truncated,
        "warnings": sorted(set(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("keyword", nargs="?", help="Case-insensitive words over label and content")
    parser.add_argument("--cache-dir", default=".document-reader")
    parser.add_argument("--doc", help="Restrict to a doc_id")
    parser.add_argument("--block-id", help="Return exactly this block")
    parser.add_argument("--label", help="Case-insensitive label substring")
    parser.add_argument("--max-results", "--limit", type=int, default=50, help="Return at most N blocks")
    parser.add_argument(
        "--match", choices=MATCH_MODES,
        help="Blocks holding all the keyword's words (default), any of them, or the whole phrase",
    )
    parser.add_argument(
        "--order", choices=ORDERS,
        help="rank: best matches first (default); doc: the order the blocks have in the documents",
    )
    parser.add_argument("--explain", action="store_true", help="Add each result's score")
    parser.add_argument(
        "--changes", action="store_true",
        help="Report the blocks added, changed and removed since the version cached before",
    )
    add_output_argument(parser)
    args = parser.parse_args()
    try:
        if args.max_results < 1:
            raise ValueError("max-results must be positive")
        if args.changes:
            if args.keyword or args.block_id or args.label or args.match or args.order or args.explain:
                raise ValueError("--changes takes only --doc and --max-results")
            emit(changes(args.cache_dir, args.doc, args.max_results), args.output)
            return 0
        result = query(
            args.cache_dir, args.keyword, args.doc, args.block_id, args.label, args.max_results,
            match=args.match or "all", order=args.order or "rank", explain=args.explain,
        )
        emit(result, args.output)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
