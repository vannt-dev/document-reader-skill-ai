"""Chart data and SmartArt text in .pptx, .docx and .xlsx."""

import json
import zipfile

import pytest

import build_cache
import doc_text
import graphics_text
import inspect_excel
import query_cache
import read_docx
import read_pptx
from conftest import REL_NS, REL_TYPE, pptx_shape, write_docx, write_pptx

C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
DGM_NS = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def _cache(values, kind="str"):
    points = "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(values) if v is not None)
    return f'<c:{kind}Cache><c:ptCount val="{len(values)}"/>{points}</c:{kind}Cache>'


def chart_xml(title, categories, series, group="barChart"):
    """A chart part with its data cached, as Office saves it. `series` is [(name, values)]."""
    body = "".join(
        "<c:ser>"
        f"<c:tx><c:strRef><c:f>Sheet1!$B$1</c:f>{_cache([name])}</c:strRef></c:tx>"
        f"<c:cat><c:strRef><c:f>Sheet1!$A$2</c:f>{_cache(categories)}</c:strRef></c:cat>"
        f"<c:val><c:numRef><c:f>Sheet1!$B$2</c:f>{_cache(values, 'num')}</c:numRef></c:val>"
        "</c:ser>"
        for name, values in series
    )
    heading = (
        f"<c:title><c:tx><c:rich><a:bodyPr/><a:p><a:r><a:t>{title}</a:t></a:r></a:p></c:rich></c:tx></c:title>"
        if title else ""
    )
    return (
        f'<c:chartSpace xmlns:c="{C_NS}" xmlns:a="{A_NS}"><c:chart>{heading}'
        f"<c:plotArea><c:{group}>{body}</c:{group}></c:plotArea></c:chart></c:chartSpace>"
    )


def smartart_xml(tree):
    """A SmartArt data part. `tree` is [(text, [children...])]; the points are stored out of order."""
    points = ['<dgm:pt modelId="doc" type="doc"/>']
    connections = []
    counter = [0]

    def add(parent, nodes):
        for position, (text, children) in enumerate(nodes):
            counter[0] += 1
            model_id = f"n{counter[0]}"
            points.append(
                f'<dgm:pt modelId="{model_id}"><dgm:t><a:bodyPr/><a:p><a:r><a:t>{text}</a:t></a:r></a:p></dgm:t></dgm:pt>'
            )
            # the transitions between nodes are points too, without text of their own
            points.append(f'<dgm:pt modelId="s{counter[0]}" type="sibTrans"/>')
            connections.append(f'<dgm:cxn modelId="c{counter[0]}" srcId="{parent}" destId="{model_id}" srcOrd="{position}"/>')
            connections.append(f'<dgm:cxn modelId="p{counter[0]}" type="presOf" srcId="{model_id}" destId="doc"/>')
            add(model_id, children)

    add("doc", tree)
    return (
        f'<dgm:dataModel xmlns:dgm="{DGM_NS}" xmlns:a="{A_NS}">'
        f'<dgm:ptLst>{"".join(reversed(points))}</dgm:ptLst><dgm:cxnLst>{"".join(connections)}</dgm:cxnLst>'
        "</dgm:dataModel>"
    )


def rels(items):
    body = "".join(f'<Relationship Id="{rid}" Type="{REL_TYPE}/{kind}" Target="{target}"/>' for rid, kind, target in items)
    return f'<Relationships xmlns="{REL_NS}">{body}</Relationships>'


def graphic_data(kind, rid):
    if kind == "chart":
        inner = f'<c:chart xmlns:c="{C_NS}" xmlns:r="{R_NS}" r:id="{rid}"/>'
        uri = C_NS
    else:
        inner = f'<dgm:relIds xmlns:dgm="{DGM_NS}" xmlns:r="{R_NS}" r:dm="{rid}" r:lo="x" r:qs="x" r:cs="x"/>'
        uri = DGM_NS
    return f'<a:graphic xmlns:a="{A_NS}"><a:graphicData uri="{uri}">{inner}</a:graphicData></a:graphic>'


def pptx_frame(kind, rid):
    return f"<p:graphicFrame>{graphic_data(kind, rid)}</p:graphicFrame>"


TREE = [("Plan", [("Research", []), ("Budget", [])]), ("Build", []), ("Ship", [])]
SMARTART_LINES = ["SmartArt:", "- Plan", "  - Research", "  - Budget", "- Build", "- Ship"]
CHART_LINES = [
    "Chart: Revenue by quarter (bar)",
    "Category | Revenue | Cost",
    "Q1 | 10 | 8",
    "Q2 | 12.5 | 9",
    "Q3 |  | 7",
]


@pytest.fixture
def graphics_pptx(tmp_path):
    path = write_pptx(tmp_path / "review.pptx", [
        (pptx_shape("Results", "title") + pptx_frame("chart", "rId2") + pptx_frame("diagram", "rId3"), None),
    ])
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", rels([
            ("rId2", "chart", "../charts/chart7.xml"), ("rId3", "diagramData", "../diagrams/data1.xml"),
        ]))
        archive.writestr("ppt/charts/chart7.xml", chart_xml(
            "Revenue by quarter", ["Q1", "Q2", "Q3"], [("Revenue", [10, 12.5, None]), ("Cost", [8, 9, 7])],
        ))
        archive.writestr("ppt/diagrams/data1.xml", smartart_xml(TREE))
    return path


def test_pptx_reads_chart_data_and_smartart_text_in_shape_order(graphics_pptx):
    slides = doc_text.pptx_slides(graphics_pptx)

    assert slides[0]["title"] == "Results"
    assert slides[0]["lines"] == CHART_LINES + SMARTART_LINES
    content = read_pptx.read(graphics_pptx, None, 12000)["content"]
    assert content.startswith("--- slide 1 ---\n# Results\nChart: Revenue by quarter (bar)\n")
    assert "  - Budget" in content


def test_docx_chart_and_smartart_follow_their_paragraph(tmp_path):
    def drawing(kind, rid):
        return f"<w:p><w:r><w:drawing>{graphic_data(kind, rid)}</w:drawing></w:r></w:p>"

    body = (
        "<w:p><w:r><w:t>Before the chart.</w:t></w:r></w:p>" + drawing("chart", "rId5")
        + "<w:p><w:r><w:t>Between.</w:t></w:r></w:p>" + drawing("diagram", "rId6")
        + "<w:p><w:r><w:t>After.</w:t></w:r></w:p>"
    )
    path = write_docx(tmp_path / "report.docx", body, parts={
        "word/_rels/document.xml.rels": rels([
            ("rId5", "chart", "charts/chart1.xml"), ("rId6", "diagramData", "diagrams/data1.xml"),
        ]),
        "word/charts/chart1.xml": chart_xml(None, ["North", "South"], [("Units", [3, 4])], group="pieChart"),
        "word/diagrams/data1.xml": smartart_xml(TREE),
    })

    items = doc_text.docx_items(path)
    assert [(item["index"], item["kind"], item["text"]) for item in items] == [
        (1, "paragraph", "Before the chart."),
        (2, "paragraph", "Chart (pie)"),
        (3, "table_row", "Category | Units"),
        (4, "table_row", "North | 3"),
        (5, "table_row", "South | 4"),
        (6, "paragraph", "Between."),
        *[(7 + i, "paragraph", line) for i, line in enumerate(SMARTART_LINES)],
        (13, "paragraph", "After."),
    ]
    outline = read_docx.outline(path)
    assert outline["table_rows"] == 3
    assert "North | 3" in read_docx.read(path, None, 1, 5, 12000)["content"]


def test_docx_chart_in_a_table_cell_follows_its_row_once(tmp_path):
    drawing = f"<w:p><w:r><w:drawing>{graphic_data('chart', 'rId5')}</w:drawing></w:r></w:p>"
    body = (
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Sales</w:t></w:r></w:p></w:tc>"
        f"<w:tc>{drawing}</w:tc></w:tr></w:tbl>"
    )
    path = write_docx(tmp_path / "table.docx", body, parts={
        "word/_rels/document.xml.rels": rels([("rId5", "chart", "/word/charts/chart1.xml")]),
        "word/charts/chart1.xml": chart_xml("Units", ["A"], [("2026", [5])]),
    })

    assert [item["text"] for item in doc_text.docx_items(path)] == [
        "Sales | ", "Chart: Units (bar)", "Category | 2026", "A | 5",
    ]


def _xlsx_with_chart(tmp_path):
    """A workbook with a chart written by openpyxl, which keeps no copy of the chart's data."""
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference

    path = tmp_path / "sales.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales data"
    for row in [["Quarter", "Revenue"], ["Q1", 10], ["Q2", 12]]:
        sheet.append(row)
    chart = BarChart()
    chart.title = "Revenue"
    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=3), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=3))
    sheet.add_chart(chart, "D2")
    workbook.save(path)
    return path


def test_xlsx_chart_without_cached_data_reads_the_cells_it_names(tmp_path):
    path = _xlsx_with_chart(tmp_path)
    assert b"Cache" not in zipfile.ZipFile(path).read("xl/charts/chart1.xml")

    graphics = doc_text.xlsx_graphics(path)
    assert list(graphics) == ["Sales data"]
    [chart] = graphics["Sales data"]
    assert (chart["title"], chart["chart_type"]) == ("Revenue", "bar")
    assert chart["tables"] == [{"headers": ["Category", "Revenue"], "rows": [["Q1", 10], ["Q2", 12]]}]


def test_xlsx_chart_sheet_is_listed_with_its_chart(tmp_path, monkeypatch, capsys):
    from openpyxl import Workbook
    from openpyxl.chart import PieChart, Reference

    path = tmp_path / "split.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    for row in [["Region", "Share"], ["North", 60], ["South", 40]]:
        sheet.append(row)
    chart = PieChart()
    chart.title = "Split"
    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=3), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=3))
    workbook.create_chartsheet("Pie").add_chart(chart)
    workbook.save(path)

    monkeypatch.setattr("sys.argv", ["inspect_excel.py", str(path)])
    assert inspect_excel.main() == 0
    sheets = json.loads(capsys.readouterr().out)["sheets"]
    assert [sheet["name"] for sheet in sheets] == ["Data", "Pie"]
    assert "graphics" not in sheets[0]
    assert sheets[1] == {"name": "Pie", "chart_sheet": True, "graphics": [{
        "kind": "chart", "title": "Split", "chart_type": "pie", "points": 2, "truncated": False,
        "tables": [{"headers": ["Category", "Share"], "rows": [["North", 60], ["South", 40]]}],
    }]}


def test_xlsx_cached_chart_and_smartart_in_inspect_and_cache(tmp_path, manifest_for, monkeypatch, capsys):
    path = _xlsx_with_chart(tmp_path)
    # Replace the chart with one that keeps its data, as Excel saves it, and add a SmartArt diagram.
    with zipfile.ZipFile(path) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    parts["xl/charts/chart1.xml"] = chart_xml("Revenue", ["Q1", "Q2"], [("Revenue", [11, 13])]).encode()
    drawing = parts["xl/drawings/drawing1.xml"].decode()
    frame = (
        f'<graphicFrame xmlns="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing">'
        f'{graphic_data("diagram", "rId9")}</graphicFrame>'
    )
    parts["xl/drawings/drawing1.xml"] = drawing.replace("</wsDr>", f"<oneCellAnchor>{frame}</oneCellAnchor></wsDr>").encode()
    drawing_rels = parts["xl/drawings/_rels/drawing1.xml.rels"].decode()
    parts["xl/drawings/_rels/drawing1.xml.rels"] = drawing_rels.replace(
        "</Relationships>",
        f'<Relationship Id="rId9" Type="{REL_TYPE}/diagramData" Target="/xl/diagrams/data1.xml"/></Relationships>',
    ).encode()
    parts["xl/diagrams/data1.xml"] = smartart_xml([("Collect", []), ("Report", [])]).encode()
    with zipfile.ZipFile(path, "w") as target:
        for name, data in parts.items():
            target.writestr(name, data)

    monkeypatch.setattr("sys.argv", ["inspect_excel.py", str(path)])
    assert inspect_excel.main() == 0
    sheet = json.loads(capsys.readouterr().out)["sheets"][0]
    assert sheet["name"] == "Sales data"
    assert sheet["graphics"] == [
        {
            "kind": "chart", "title": "Revenue", "chart_type": "bar", "points": 2, "truncated": False,
            "tables": [{"headers": ["Category", "Revenue"], "rows": [["Q1", 11], ["Q2", 13]]}],
        },
        {"kind": "smartart", "lines": ["- Collect", "- Report"]},
    ]

    cache_dir = tmp_path / ".document-reader"
    index = build_cache.build(manifest_for([path], cache_dir), cache_dir, window=500)
    blocks = index["documents"][0]["blocks"]
    assert [(block["block_id"], block["label"]) for block in blocks] == [
        ("Sales data!A1:B3", "Sales data"),
        ("Sales data!chart-1", "Sales data chart 1: Revenue"),
        ("Sales data!smartart-1", "Sales data SmartArt 1"),
    ]
    cached = json.loads((cache_dir / "cache" / "sales-xlsx.json").read_text(encoding="utf-8"))
    assert cached["blocks"][1]["content"] == {"text": "Chart: Revenue (bar)\nCategory | Revenue\nQ1 | 11\nQ2 | 13"}
    result = query_cache.query(cache_dir, keyword="Collect")
    assert [(r["block_id"], r["ref"]) for r in result["results"]] == [
        ("Sales data!smartart-1", {"sheet": "Sales data", "smartart": 1}),
    ]


def test_chart_data_scatter_multi_level_categories_and_truncation(monkeypatch):
    scatter = (
        f'<c:chartSpace xmlns:c="{C_NS}"><c:chart><c:plotArea><c:scatterChart><c:ser>'
        f"<c:tx><c:v>Load</c:v></c:tx>"
        f"<c:xVal><c:numRef><c:f>A</c:f>{_cache([1, 2], 'num')}</c:numRef></c:xVal>"
        f"<c:yVal><c:numRef><c:f>B</c:f>{_cache([0.5, 0.75], 'num')}</c:numRef></c:yVal>"
        "</c:ser></c:scatterChart></c:plotArea></c:chart></c:chartSpace>"
    )
    assert graphics_text.graphic_lines(graphics_text.chart_data(scatter.encode())) == [
        "Chart (scatter)", "X | Load", "1 | 0.5", "2 | 0.75",
    ]

    multi = (
        f'<c:chartSpace xmlns:c="{C_NS}"><c:chart><c:plotArea><c:lineChart><c:ser>'
        "<c:cat><c:multiLvlStrRef><c:multiLvlStrCache><c:ptCount val=\"3\"/>"
        '<c:lvl><c:pt idx="0"><c:v>Q1</c:v></c:pt><c:pt idx="1"><c:v>Q2</c:v></c:pt><c:pt idx="2"><c:v>Q1</c:v></c:pt></c:lvl>'
        '<c:lvl><c:pt idx="0"><c:v>2025</c:v></c:pt><c:pt idx="2"><c:v>2026</c:v></c:pt></c:lvl>'
        "</c:multiLvlStrCache></c:multiLvlStrRef></c:cat>"
        f"<c:val><c:numLit>{_cache([1, 2, 3], 'num')[len('<c:numCache>'):-len('</c:numCache>')]}</c:numLit></c:val>"
        "</c:ser></c:lineChart><c:barChart><c:ser><c:val><c:numLit><c:ptCount val=\"3\"/></c:numLit></c:val>"
        "</c:ser></c:barChart></c:plotArea></c:chart></c:chartSpace>"
    )
    chart = graphics_text.chart_data(multi.encode())
    assert chart["chart_type"] == "line+bar"
    assert chart["tables"][0] == {
        "headers": ["Category", "Series 1"],
        "rows": [["2025 / Q1", 1], ["2025 / Q2", 2], ["2026 / Q1", 3]],
    }

    monkeypatch.setattr(graphics_text, "MAX_CHART_POINTS", 2)
    cut = graphics_text.chart_data(chart_xml("Big", ["a", "b", "c"], [("S", [1, 2, 3])]).encode())
    lines = graphics_text.graphic_lines(cut)
    assert lines[0] == "Chart: Big (bar; first 2 of 3 points)"
    assert lines[1:] == ["Category | S", "a | 1", "b | 2"]


def test_a_newer_chart_type_is_named_not_read_and_the_fallback_is_not_read_twice(tmp_path):
    chartex = (
        f'<mc:AlternateContent xmlns:mc="{MC_NS}"><mc:Choice Requires="cx1"><p:graphicFrame>'
        f'<a:graphic xmlns:a="{A_NS}"><a:graphicData uri="http://schemas.microsoft.com/office/drawing/2014/chartex"/>'
        "</a:graphic></p:graphicFrame></mc:Choice>"
        f"<mc:Fallback>{pptx_shape('This chart is not available in your version.')}</mc:Fallback>"
        "</mc:AlternateContent>"
    )
    path = write_pptx(tmp_path / "waterfall.pptx", [(pptx_shape("Cash flow", "title") + chartex, None)])

    slide = doc_text.pptx_slides(path)[0]
    assert slide["lines"] == ["[chart of a newer Office type (waterfall, treemap ...): not read]"]


def test_python_pptx_chart_is_read_like_office_saves_it(tmp_path):
    pptx = pytest.importorskip("pptx")
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches

    deck = pptx.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = "Quarterly sales"
    data = CategoryChartData()
    data.categories = ["Q1", "Q2", "Q3"]
    data.add_series("Revenue", (10, 12.5, 9))
    data.add_series("Cost", (8, 9, 7))
    frame = slide.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(1), Inches(1), Inches(6), Inches(4), data)
    frame.chart.has_title = True
    frame.chart.chart_title.text_frame.text = "Revenue and cost"
    path = tmp_path / "generated.pptx"
    deck.save(path)

    lines = doc_text.pptx_slides(path)[0]["lines"]
    assert lines == [
        "Chart: Revenue and cost (line)",
        "Category | Revenue | Cost",
        "Q1 | 10 | 8",
        "Q2 | 12.5 | 9",
        "Q3 | 9 | 7",
    ]
