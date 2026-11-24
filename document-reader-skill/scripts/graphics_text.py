"""Chart data and SmartArt text of Office documents (.pptx, .docx, .xlsx).

A chart part keeps a copy of its data (the values as they were when the file
was last saved): its title, the name of each series, the categories and the
values. A SmartArt diagram keeps its text in a data part, as a tree of nodes.
Both are read here with the standard library only; nothing is recalculated,
no embedded workbook is opened and no external link is followed.

The callers find the parts: `frame_graphics` is given an element of a slide,
a paragraph or a sheet drawing, the relationships of the part that holds it,
and a function that reads a part of the package.
"""

from __future__ import annotations

from typing import Callable, Iterator
from xml.etree import ElementTree

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
DGM = "{http://schemas.openxmlformats.org/drawingml/2006/diagram}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
CHART_URI = "http://schemas.openxmlformats.org/drawingml/2006/chart"
DIAGRAM_URI = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
# Charts added in Office 2016 (waterfall, treemap, sunburst, histogram, box and
# whisker, funnel, map) are stored in another format, which is not read.
CHARTEX_URI = "http://schemas.microsoft.com/office/drawing/2014/chartex"
# A chart with more points than this is cut, and says so.
MAX_CHART_POINTS = 500

Values = dict[int, object]
Resolve = Callable[[str], list]


def _number(text: str) -> object:
    try:
        value = float(text)
    except ValueError:
        return text
    return int(value) if value.is_integer() and "e" not in text.lower() else value


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace("\n", " ")


def _cache_points(cache, numeric: bool) -> tuple[Values, int]:
    """The points of a `c:strCache`, `c:numCache` or literal, by index, and how many it declares."""
    points: Values = {}
    for point in cache.findall(f"{C}pt"):
        value = point.find(f"{C}v")
        if value is None or value.text is None:
            continue
        try:
            index = int(point.get("idx", "0"))
        except ValueError:
            continue
        points[index] = _number(value.text) if numeric else value.text
    count = cache.find(f"{C}ptCount")
    try:
        declared = int(count.get("val", "0")) if count is not None else 0
    except ValueError:
        declared = 0
    return points, max(declared, max(points, default=-1) + 1)


def _multi_level(cache) -> tuple[Values, int]:
    """Categories in several levels (`c:multiLvlStrCache`): `Year / Quarter` labels.

    The first level is the innermost one; an outer label is stored once, at the
    first category of its group, and holds for the ones after it.
    """
    levels = [_cache_points(level, False)[0] for level in cache.findall(f"{C}lvl")]
    _, count = _cache_points(cache, False)
    count = max([count] + [max(level, default=-1) + 1 for level in levels])
    labels: Values = {}
    carried = [None] * len(levels)
    for index in range(count):
        parts = []
        for depth in range(len(levels) - 1, -1, -1):
            if index in levels[depth]:
                carried[depth] = levels[depth][index]
            if carried[depth] is not None:
                parts.append(str(carried[depth]))
        if parts:
            labels[index] = " / ".join(parts)
    return labels, count


def _data(source, resolve: Resolve | None) -> tuple[Values, int]:
    """The points of `c:tx`, `c:cat`, `c:val`, `c:xVal` or `c:yVal`, by index."""
    if source is None:
        return {}, 0
    if source.find(f"{C}v") is not None:  # a series name written as text
        return {0: source.find(f"{C}v").text or ""}, 1
    for ref, cache, numeric in (
        ("numRef", "numCache", True), ("strRef", "strCache", False), (None, "numLit", True),
        (None, "strLit", False), ("multiLvlStrRef", "multiLvlStrCache", False),
    ):
        holder = source.find(f"{C}{ref}") if ref else source
        if holder is None:
            continue
        found = holder.find(f"{C}{cache}")
        if found is not None:
            return _multi_level(found) if cache == "multiLvlStrCache" else _cache_points(found, numeric)
        formula = holder.find(f"{C}f") if ref else None
        if formula is not None and formula.text and resolve is not None:
            # No copy of the data in the chart (files written by some libraries):
            # the cells the chart names, when the caller can read them.
            values = resolve(formula.text)
            return {index: value for index, value in enumerate(values) if value is not None}, len(values)
    return {}, 0


def _rich_text(element) -> str:
    texts = []
    for paragraph in element.iter(f"{A}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{A}t")).strip()
        if text:
            texts.append(text)
    return " ".join(texts)


def _title(chart) -> str | None:
    title = chart.find(f"{C}title")
    if title is None:
        return None
    text = title.find(f"{C}tx")
    if text is None:
        return None
    rich = text.find(f"{C}rich")
    if rich is not None:
        return _rich_text(rich) or None
    points, _ = _data(text, None)
    return _cell(points.get(0)) or None


def _kind(tag: str) -> str:
    name = tag.rsplit("}", 1)[-1].removesuffix("Chart").replace("3D", "")
    return {"ofPie": "pie", "doughnut": "doughnut"}.get(name, name)


def chart_data(xml: bytes, resolve: Resolve | None = None) -> dict:
    """A chart part as `title`, `chart_type` (`bar`, `line`, `bar+line` ...) and `tables`.

    Each table has `headers` (the category column, then one column a series) and
    `rows` of cells; series that share their categories share a table. `points`
    is how many categories there are, and `truncated` says the rows stop at
    MAX_CHART_POINTS. `resolve` reads the cells a series names when the chart
    holds no copy of its data.
    """
    root = ElementTree.fromstring(xml)
    chart = root.find(f"{C}chart")
    if chart is None:
        return {"kind": "chart", "title": None, "chart_type": None, "tables": [], "points": 0, "truncated": False}
    plot = chart.find(f"{C}plotArea")
    kinds: list[str] = []
    groups: list[dict] = []
    points = numbered = 0
    for group in plot if plot is not None else ():
        if not group.tag.endswith("Chart"):
            continue
        kind = _kind(group.tag)
        if kind not in kinds:
            kinds.append(kind)
        scatter = kind in ("scatter", "bubble")
        for series in group.findall(f"{C}ser"):
            name, _ = _data(series.find(f"{C}tx"), resolve)
            categories, count = _data(series.find(f"{C}xVal" if scatter else f"{C}cat"), resolve)
            values, value_count = _data(series.find(f"{C}yVal" if scatter else f"{C}val"), resolve)
            count = max(count, value_count)
            points = max(points, count)
            numbered += 1
            label = _cell(name.get(0)) or f"Series {numbered}"
            # Series with the same categories share a table; without categories, the same number of points.
            key = (scatter, tuple(sorted(categories.items())), 0 if categories else count)
            for existing in groups:
                if existing["key"] == key:
                    existing["series"].append((label, values))
                    existing["count"] = max(existing["count"], count)
                    break
            else:
                groups.append({
                    "key": key, "categories": categories, "count": count,
                    "first": "X" if scatter else "Category", "series": [(label, values)],
                })
    tables = []
    for group in groups:
        shown = min(group["count"], MAX_CHART_POINTS)
        tables.append({
            "headers": [group["first"]] + [label for label, _ in group["series"]],
            "rows": [
                [group["categories"].get(index, index + 1 if not group["categories"] else None)]
                + [values.get(index) for _, values in group["series"]]
                for index in range(shown)
            ],
        })
    return {
        "kind": "chart", "title": _title(chart), "chart_type": "+".join(kinds) or None,
        "tables": tables, "points": points, "truncated": points > MAX_CHART_POINTS,
    }


def smartart_data(xml: bytes) -> dict:
    """A SmartArt data part as `lines`: the text of each node, indented by its depth.

    The nodes are read in the order the diagram shows them, from its tree of
    parent-child connections; a diagram whose tree cannot be followed lists its
    nodes in the order they are stored.
    """
    root = ElementTree.fromstring(xml)
    points = {}
    order = []
    for point in root.iter(f"{DGM}pt"):
        model_id = point.get("modelId")
        if model_id is None:
            continue
        text_body = point.find(f"{DGM}t")
        points[model_id] = {
            "type": point.get("type", "node"),
            "text": _rich_text(text_body).replace("\n", " ") if text_body is not None else "",
        }
        order.append(model_id)
    children: dict[str, list[tuple[int, str]]] = {}
    for connection in root.iter(f"{DGM}cxn"):
        if connection.get("type", "parOf") != "parOf":
            continue
        source, target = connection.get("srcId"), connection.get("destId")
        if source is None or target is None:
            continue
        try:
            position = int(connection.get("srcOrd", "0"))
        except ValueError:
            position = 0
        children.setdefault(source, []).append((position, target))
    lines: list[str] = []
    seen: set[str] = set()

    def visit(model_id: str, depth: int) -> None:
        for _, child in sorted(children.get(model_id, [])):
            if child in seen or child not in points:
                continue
            seen.add(child)
            point = points[child]
            shown = point["type"] in ("node", "asst") and point["text"]
            if shown:
                lines.append(f"{'  ' * depth}- {point['text']}")
            visit(child, depth + 1 if shown else depth)

    for model_id in order:
        if points[model_id]["type"] == "doc":
            seen.add(model_id)
            visit(model_id, 0)
    if not lines:
        lines = [
            f"- {points[m]['text']}" for m in order if points[m]["type"] in ("node", "asst") and points[m]["text"]
        ]
    return {"kind": "smartart", "lines": lines}


def graphic_lines(graphic: dict) -> list[str]:
    """A chart or a SmartArt diagram as lines of text: a table row is `cell | cell`."""
    if graphic["kind"] == "smartart":
        return ["SmartArt:"] + graphic["lines"] if graphic["lines"] else []
    if graphic["kind"] == "unread":
        return [f"[{graphic['note']}]"]
    about = [graphic["chart_type"]] if graphic["chart_type"] else []
    if graphic["truncated"]:
        about.append(f"first {MAX_CHART_POINTS} of {graphic['points']} points")
    head = f"Chart: {graphic['title']}" if graphic["title"] else "Chart"
    lines = [f"{head} ({'; '.join(about)})" if about else head]
    for table in graphic["tables"]:
        lines.append(" | ".join(table["headers"]))
        lines.extend(" | ".join(_cell(value) for value in row) for row in table["rows"])
    return lines


def _without_fallback(element) -> Iterator:
    """Every element under `element`, leaving out the legacy copy a drawing may keep (`mc:Fallback`)."""
    for child in element:
        if child.tag == MC_FALLBACK:
            continue
        yield child
        yield from _without_fallback(child)


def frame_graphics(
    element, relationships: dict[str, dict], read: Callable[[str], bytes | None],
    resolve: Resolve | None = None,
) -> list[dict]:
    """The charts and SmartArt diagrams under `element`, in document order.

    `relationships` are those of the part `element` belongs to (id to target
    part name), `read` returns a part's bytes or None. A chart in a format this
    module does not read is listed as `unread`, so that the reader knows it is there.
    """
    graphics = []
    for node in _without_fallback(element):
        if node.tag != f"{A}graphicData":
            continue
        uri = node.get("uri")
        if uri == CHART_URI:
            reference = node.find(f"{C}chart")
            target = relationships.get(reference.get(f"{R}id", "") if reference is not None else "")
            data = read(target["target"]) if target else None
            if data is not None:
                graphics.append(chart_data(data, resolve))
        elif uri == DIAGRAM_URI:
            reference = node.find(f"{DGM}relIds")
            target = relationships.get(reference.get(f"{R}dm", "") if reference is not None else "")
            data = read(target["target"]) if target else None
            if data is not None:
                graphics.append(smartart_data(data))
        elif uri == CHARTEX_URI:
            note = "chart of a newer Office type (waterfall, treemap ...): not read"
            graphics.append({"kind": "unread", "note": note})
    return graphics
