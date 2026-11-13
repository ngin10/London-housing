"""Generate the Power BI project (powerbi/london_property.pbip) from code.

    python -m src.export_powerbi
    python -m src.make_pbip

Writes a Power BI Project: the semantic model as TMDL (tables, Power Query, relationships,
date table, sort orders, and every measure in powerbi/measures.dax) and a four-page
report. Open london_property.pbip in Power BI Desktop and click Refresh to load the data.

The CSV folder is a model parameter (DataFolder). If the repo moves, change it in
Transform data > Manage parameters, or re-run this script.
"""
import json
import re
import uuid

from src.config import ROOT

PBI = ROOT / "powerbi"
NAME = "london_property"
MODEL = PBI / f"{NAME}.SemanticModel"
REPORT = PBI / f"{NAME}.Report"
DATA_DIR = PBI / "data"

# ---------------------------------------------------------------- tables
# (column, TMDL dataType, Power Query type, summarizeBy, extra properties)
T, I, D, DT = "string", "int64", "double", "dateTime"
PQ = {T: "type text", I: "Int64.Type", D: "type number", DT: "type date"}

TABLES = {
    "fact_sales": [
        ("transaction_id", T, {}), ("sale_date", DT, {"formatString": "dd mmm yyyy"}),
        ("price", I, {"formatString": "£#,0"}),
        ("price_band", T, {"sortByColumn": "price_band_order"}),
        ("price_band_order", I, {"isHidden": True}),
        ("borough", T, {}), ("property_type", T, {}), ("tenure", T, {}), ("new_build", T, {}),
        ("postcode", T, {}), ("outward_code", T, {}), ("postcode_sector", T, {}),
        ("lsoa_code", T, {}),
        ("latitude", D, {"dataCategory": "Latitude"}), ("longitude", D, {"dataCategory": "Longitude"}),
        ("crimes_12m", D, {}), ("burglaries_12m", D, {}),
    ],
    "fact_valuation_test": [
        ("transaction_id", T, {}), ("pred_price", D, {"formatString": "£#,0"}),
        ("baseline_price", D, {"formatString": "£#,0"}),
        ("model_ape", D, {"formatString": "0.0%"}), ("baseline_ape", D, {"formatString": "0.0%"}),
        ("model_within_10pct", I, {}), ("model_within_20pct", I, {}),
        ("predicted_band", T, {"sortByColumn": "predicted_band_order"}),
        ("predicted_band_order", I, {"isHidden": True}),
    ],
    "dim_date": [
        ("date", DT, {"isKey": True, "formatString": "dd mmm yyyy"}), ("year", I, {}),
        ("month_number", I, {}), ("month_start", DT, {"formatString": "mmm yyyy"}),
        ("month_label", T, {"sortByColumn": "year_month"}), ("year_month", T, {}),
        ("quarter", T, {}), ("weekday", T, {"sortByColumn": "weekday_number"}),
        ("weekday_number", I, {"isHidden": True}), ("sdlt_period", T, {}),
    ],
    "dim_borough": [
        ("borough", T, {}), ("inner_outer", T, {}), ("sales_count", I, {}), ("coverage", T, {}),
    ],
    "dim_property_type": [
        ("property_type", T, {"sortByColumn": "type_order"}), ("type_order", I, {"isHidden": True}),
        ("is_house", T, {}),
    ],
    "data_quality_funnel": [
        ("step_order", I, {"isHidden": True}), ("step", T, {"sortByColumn": "step_order"}),
        ("rows_remaining", I, {"formatString": "#,0"}), ("rows_removed", I, {"formatString": "#,0"}),
    ],
}

RELATIONSHIPS = [  # (from many, to one)
    ("fact_sales", "sale_date", "dim_date", "date"),
    ("fact_sales", "borough", "dim_borough", "borough"),
    ("fact_sales", "property_type", "dim_property_type", "property_type"),
    ("fact_valuation_test", "transaction_id", "fact_sales", "transaction_id"),
]


def q(name: str) -> str:
    """Quote a TMDL object name when it isn't a plain identifier."""
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else "'" + name.replace("'", "''") + "'"


def tag() -> str:
    return str(uuid.uuid4())


def table_tmdl(name: str, cols) -> str:
    lines = [f"table {q(name)}", f"\tlineageTag: {tag()}"]
    if name == "dim_date":
        lines.append("\tdataCategory: Time")
    lines.append("")
    for col, dtype, props in cols:
        lines += [f"\tcolumn {q(col)}", f"\t\tdataType: {dtype}"]
        for k in ("isKey", "isHidden"):
            if props.get(k):
                lines.append(f"\t\t{k}")
        for k in ("formatString", "dataCategory", "sortByColumn"):
            if k in props:
                lines.append(f"\t\t{k}: {props[k]}")
        lines += [f"\t\tlineageTag: {tag()}", "\t\tsummarizeBy: none", f"\t\tsourceColumn: {col}", ""]
    types = ", ".join(f'{{"{c}", {PQ[t]}}}' for c, t, _ in cols)
    m = [
        "let",
        f'    Source = Csv.Document(File.Contents(DataFolder & "{name}.csv"), '
        f'[Delimiter=",", Columns={len(cols)}, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
        f'    Typed = Table.TransformColumnTypes(Promoted, {{{types}}}, "en-GB")',
        "in",
        "    Typed",
    ]
    lines += [f"\tpartition {q(name)} = m", "\t\tmode: import", "\t\tsource ="]
    lines += ["\t\t\t\t" + x for x in m]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- measures
def parse_measures(path):
    """Read powerbi/measures.dax: 'Name = expression' blocks, grouped by '// ---- folder' comments."""
    measures, folder, cur = [], "", None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        head = re.match(r"^// -+\s*(.+)$", line)
        if head:
            folder = head.group(1).strip().capitalize()
            continue
        if line.startswith("//"):
            continue
        if not line:                       # a blank line ends the current measure
            cur = None
            continue
        if cur is None:                    # first line of a block: "Name = [expression]"
            start = re.match(r"^([A-Za-z][^=]*?)\s*=\s*(.*)$", line)
            if not start:
                raise ValueError(f"Can't parse measure start: {line!r}")
            cur = {"name": start.group(1).strip(), "expr": [start.group(2)] if start.group(2) else [],
                   "folder": folder}
            measures.append(cur)
        else:
            cur["expr"].append(line)
    return measures


def measure_format(name: str) -> str | None:
    if name.startswith("Title") or name == "Borough Coverage":
        return None
    if "vs Jan-Feb" in name:
        return '0.0"×"'
    if any(w in name for w in ("%", "Share", "Within", "Reduction")):
        return "0.0%"
    if any(w in name for w in ("Price", "Value")):
        return "£#,0"
    return "#,0"


def measures_tmdl(measures) -> str:
    lines = ["table _Measures", f"\tlineageTag: {tag()}", ""]
    for m in measures:
        expr = [e.strip() if i == 0 else e for i, e in enumerate(m["expr"])]
        if len(expr) == 1:
            lines.append(f"\tmeasure {q(m['name'])} = {expr[0]}")
        else:
            lines.append(f"\tmeasure {q(m['name'])} = ```")
            lines += ["\t\t\t" + e for e in expr]
            lines.append("\t\t\t```")
        fmt = measure_format(m["name"])
        if fmt:
            lines.append(f"\t\tformatString: {fmt}")
        if m["folder"]:
            lines.append(f"\t\tdisplayFolder: {m['folder']}")
        lines += [f"\t\tlineageTag: {tag()}", ""]
    lines += ["\tcolumn Value", "\t\tdataType: string", "\t\tisHidden", f"\t\tlineageTag: {tag()}",
              "\t\tsummarizeBy: none", "\t\tsourceColumn: Value", "",
              "\tpartition _Measures = m", "\t\tmode: import", "\t\tsource =",
              '\t\t\t\t#table(type table [Value = text], {})', ""]
    return "\n".join(lines)


def write_model(measures) -> None:
    d = MODEL / "definition"
    (d / "tables").mkdir(parents=True, exist_ok=True)
    for old in (d / "tables").glob("*.tmdl"):
        old.unlink()
    (MODEL / "definition.pbism").write_text(json.dumps({"version": "4.2", "settings": {}}, indent=2))
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1600\n", encoding="utf-8")
    names = ["_Measures", *TABLES]
    (d / "model.tmdl").write_text("\n".join([
        "model Model",
        "\tculture: en-GB",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tsourceQueryCulture: en-GB",
        "\tdataAccessOptions",
        "\t\tlegacyRedirects",
        "\t\treturnErrorValuesAsNull",
        "",
        "annotation __PBI_TimeIntelligenceEnabled = 0",
        "",
        *[f"ref table {q(n)}" for n in names],
        "",
    ]), encoding="utf-8")
    folder = str(DATA_DIR) + "\\"          # M text has no backslash escapes
    (d / "expressions.tmdl").write_text(
        f'expression DataFolder = "{folder}" meta [IsParameterQuery=true, Type="Text", '
        f'IsParameterQueryRequired=true]\n\tlineageTag: {tag()}\n\n'
        "\tannotation PBI_ResultType = Text\n", encoding="utf-8")
    for name, cols in TABLES.items():
        (d / "tables" / f"{name}.tmdl").write_text(table_tmdl(name, cols), encoding="utf-8")
    (d / "tables" / "_Measures.tmdl").write_text(measures_tmdl(measures), encoding="utf-8")
    rel = []
    for ft, fc, tt, tc in RELATIONSHIPS:
        rel += [f"relationship {tag()}", f"\tfromColumn: {q(ft)}.{q(fc)}", f"\ttoColumn: {q(tt)}.{q(tc)}", ""]
    (d / "relationships.tmdl").write_text("\n".join(rel), encoding="utf-8")


# ---------------------------------------------------------------- report
INK, TEAL, BRASS, GREY = "#16233B", "#0E7C86", "#C99A2E", "#C9D0D8"


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def colour(hex_):
    return {"solid": {"color": lit(f"'{hex_}'")}}


class Q:
    """Builds a visual's prototypeQuery and its role projections."""

    def __init__(self):
        self.sources, self.select, self.proj = {}, [], {}

    def _src(self, entity):
        if entity not in self.sources:
            self.sources[entity] = f"s{len(self.sources)}"
        return {"SourceRef": {"Source": self.sources[entity]}}

    def measure(self, role, name, entity="_Measures"):
        ref = f"{entity}.{name}"
        self.select.append({"Measure": {"Expression": self._src(entity), "Property": name},
                            "Name": ref, "NativeReferenceName": name})
        self.proj.setdefault(role, []).append({"queryRef": ref})
        return self

    def column(self, role, entity, name):
        ref = f"{entity}.{name}"
        self.select.append({"Column": {"Expression": self._src(entity), "Property": name},
                            "Name": ref, "NativeReferenceName": name})
        self.proj.setdefault(role, []).append({"queryRef": ref, **({"active": True} if role == "Category" else {})})
        return self

    def sum(self, role, entity, name):
        ref = f"Sum({entity}.{name})"
        self.select.append({"Aggregation": {"Expression": {"Column": {"Expression": self._src(entity),
                                                                     "Property": name}}, "Function": 0},
                            "Name": ref, "NativeReferenceName": name})
        self.proj.setdefault(role, []).append({"queryRef": ref})
        return self

    def query(self, order=None):
        qd = {"Version": 2,
              "From": [{"Name": s, "Entity": e, "Type": 0} for e, s in self.sources.items()],
              "Select": self.select}
        if order:
            kind, entity, name, direction = order
            expr = ({"Measure": {"Expression": self._src(entity), "Property": name}} if kind == "measure"
                    else {"Column": {"Expression": self._src(entity), "Property": name}})
            qd["OrderBy"] = [{"Direction": direction, "Expression": expr}]
        return qd


class Page:
    def __init__(self, name, display):
        self.name, self.display, self.visuals, self.z = name, display, [], 0

    def add(self, vtype, x, y, w, h, query=None, title=None, objects=None, order=None, vc=None):
        self.z += 1
        single = {"visualType": vtype, "drillFilterOtherVisuals": True}
        if query is not None:
            single["projections"] = query.proj
            single["prototypeQuery"] = query.query(order)
        if objects:
            single["objects"] = objects
        vco = dict(vc or {})
        if title:
            vco["title"] = [{"properties": {"show": lit("true"), "text": lit(f"'{title}'"),
                                            "fontColor": colour(INK), "fontSize": lit("12D")}}]
        if vco:
            single["vcObjects"] = vco
        name = uuid.uuid4().hex[:20]
        cfg = {"name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": self.z * 1000,
                                                                  "width": w, "height": h,
                                                                  "tabOrder": self.z * 1000}}],
               "singleVisual": single}
        self.visuals.append({"x": x, "y": y, "z": self.z * 1000, "width": w, "height": h,
                             "config": json.dumps(cfg), "filters": "[]", "tabOrder": self.z * 1000})

    def text(self, x, y, w, h, runs):
        """runs: list of paragraphs; each a list of (text, size, bold, colour)."""
        paras = [{"textRuns": [{"value": t, "textStyle": {"fontSize": f"{size}pt", "color": col,
                                                           **({"fontWeight": "bold"} if bold else {})}}
                               for t, size, bold, col in p]} for p in runs]
        self.add("textbox", x, y, w, h, objects={"general": [{"properties": {"paragraphs": paras}}]})

    def heading(self, title, sub):
        self.text(24, 12, 1000, 70, [[(title, 20, True, INK)], [(sub, 11, False, "#5B6577")]])

    def card(self, x, y, measure, label, w=220, h=110):
        self.add("card", x, y, w, h, Q().measure("Values", measure),
                 objects={"labels": [{"properties": {"color": colour(TEAL), "fontSize": lit("26D")}}],
                          "categoryLabels": [{"properties": {"show": lit("false")}}]},
                 title=label, vc={"background": [{"properties": {"color": colour("#EEF1F4")}}]})

    def slicer(self, x, y, entity, col, title, w=240, h=60):
        self.add("slicer", x, y, w, h, Q().column("Values", entity, col), title=title,
                 objects={"data": [{"properties": {"mode": lit("'Dropdown'")}}]})

    def section(self):
        return {"name": self.name, "displayName": self.display, "displayOption": 1,
                "width": 1280, "height": 720, "config": "{}", "filters": "[]",
                "visualContainers": self.visuals}


def bars(series_colour):
    return {"dataPoint": [{"properties": {"fill": colour(series_colour)}}],
            "labels": [{"properties": {"show": lit("true")}}]}


def common_slicers(p, x=1020):
    p.slicer(x, 100, "dim_borough", "borough", "Borough")
    p.slicer(x, 170, "dim_property_type", "property_type", "Property type")
    p.slicer(x, 240, "fact_sales", "tenure", "Tenure")
    p.slicer(x, 310, "dim_borough", "inner_outer", "Inner / Outer London")


def build_pages():
    S = "_Measures"
    # 1. Market overview
    p1 = Page("ReportSection1", "Market overview")
    p1.heading("London home sales, Jan 2025 - Jan 2026",
               "HM Land Registry standard sales. Use the filters on the right; every page shares them.")
    for i, (m, label) in enumerate([("Sales Count", "Sales"), ("Median Price", "Median price"),
                                    ("Leasehold Share", "Leasehold share"),
                                    ("New Build Share", "New-build share")]):
        p1.card(24 + i * 244, 100, m, label)
    p1.add("lineClusteredColumnComboChart", 24, 230, 600, 330,
           Q().column("Category", "dim_date", "month_label").measure("Y", "Sales Count")
              .measure("Y2", "Median Price 3M Rolling"),
           title="Sales per month (columns) and rolling 3-month median price (line)",
           order=("column", "dim_date", "month_label", 1),
           objects={"dataPoint": [{"properties": {"fill": colour(GREY)}}]})
    p1.add("clusteredBarChart", 640, 230, 360, 330,
           Q().column("Category", "dim_property_type", "property_type").measure("Y", "Median Price"),
           title="Median price by property type", order=("column", "dim_property_type", "property_type", 1),
           objects=bars(TEAL))
    p1.text(24, 580, 976, 110, [
        [("What happened: ", 12, True, INK),
         ("March 2025 saw 10,087 sales, 2.4× the Jan-Feb average, as buyers completed before stamp "
          "duty thresholds fell on 1 April. April dropped to 1,715. Monthly medians around the deadline "
          "mostly reflect which homes sold, so the line uses a rolling 3-month median.", 12, False, "#33415C")]])
    common_slicers(p1)

    # 2. Boroughs
    p2 = Page("ReportSection2", "Borough comparison")
    p2.heading("Where London is expensive, and where the data is thin",
               "Ranking uses only boroughs with 300+ sales in this extract.")
    p2.add("clusteredBarChart", 24, 100, 420, 600,
           Q().column("Category", "dim_borough", "borough").measure("Y", "Median Price (Reliable Boroughs)"),
           title="Median price, boroughs with 300+ sales",
           order=("measure", S, "Median Price (Reliable Boroughs)", 2), objects=bars(TEAL))
    p2.add("tableEx", 460, 100, 540, 470,
           Q().column("Values", "dim_borough", "borough").column("Values", "dim_borough", "inner_outer")
              .measure("Values", "Sales Count").measure("Values", "Median Price")
              .measure("Values", "Leasehold Share").measure("Values", "Median Crimes (12m)")
              .column("Values", "dim_borough", "coverage"),
           title="Borough summary", order=("measure", S, "Median Price", 2))
    p2.text(460, 585, 540, 115, [
        [("Coverage caveat: ", 11, True, INK),
         ("4 boroughs have fewer than 300 sales here (Sutton 1, Kingston 23). Hounslow's high median "
          "comes from W4 (Chiswick), 94% of its sales in this extract. See ISSUES.md #2.", 11, False, "#33415C")]])
    common_slicers(p2)

    # 3. Stamp duty
    p3 = Page("ReportSection3", "Stamp duty and price bands")
    p3.heading("How the 1 April 2025 stamp duty change affected sales",
               "Thresholds fell on 1 April 2025, so buyers rushed to complete in March.")
    for i, (m, label) in enumerate([("Sales Before SDLT Change", "Sales before 1 Apr 2025"),
                                    ("Sales From SDLT Change", "Sales from 1 Apr 2025"),
                                    ("March 2025 vs Jan-Feb Average", "March vs Jan-Feb average")]):
        p3.card(24 + i * 330, 100, m, label, w=310)
    p3.add("clusteredColumnChart", 24, 230, 600, 460,
           Q().column("Category", "dim_date", "month_label").column("Series", "dim_date", "sdlt_period")
              .measure("Y", "Sales Count"),
           title="Sales per month, before and after the change", order=("column", "dim_date", "month_label", 1))
    p3.add("hundredPercentStackedBarChart", 640, 230, 360, 220,
           Q().column("Category", "dim_date", "sdlt_period").column("Series", "fact_sales", "price_band")
              .measure("Y", "Sales Count"),
           title="Share of sales by price band")
    p3.add("pivotTable", 640, 465, 360, 225,
           Q().column("Rows", "dim_property_type", "property_type").column("Columns", "dim_date", "sdlt_period")
              .measure("Values", "Median Price"),
           title="Median price by type, before and after")
    common_slicers(p3)

    # 4. Data quality and accuracy
    p4 = Page("ReportSection4", "Data quality and accuracy")
    p4.heading("Can the numbers and the valuations be trusted?",
               "Cleaning funnel from src/clean.py; valuations tested on Nov 2025 - Jan 2026 sales the model never saw.")
    p4.add("funnel", 24, 100, 480, 360,
           Q().column("Category", "data_quality_funnel", "step").sum("Y", "data_quality_funnel", "rows_remaining"),
           title="Rows remaining after each cleaning rule", order=("column", "data_quality_funnel", "step", 1),
           objects={"dataPoint": [{"properties": {"fill": colour(TEAL)}}]})
    p4.card(24, 480, "Records Kept %", "Raw records kept", w=230)
    p4.card(274, 480, "Clean Records", "Clean sales", w=230)
    for i, (m, label) in enumerate([("Model Median Error %", "Model median error"),
                                    ("Baseline Median Error %", "Benchmark median error"),
                                    ("Model Within 20%", "Model within 20%")]):
        p4.card(530 + i * 250, 100, m, label, w=230)
    p4.add("clusteredColumnChart", 530, 230, 730, 260,
           Q().column("Category", "fact_valuation_test", "predicted_band")
              .measure("Y", "Model Median Error %").measure("Y", "Baseline Median Error %"),
           title="Median valuation error by predicted value: model vs benchmark",
           order=("column", "fact_valuation_test", "predicted_band", 1),
           objects={"labels": [{"properties": {"show": lit("true")}}]})
    p4.add("tableEx", 530, 505, 730, 195,
           Q().column("Values", "dim_borough", "borough").measure("Values", "Valuations Tested")
              .measure("Values", "Model Median Error %").measure("Values", "Baseline Median Error %"),
           title="Accuracy by borough (hardest first)", order=("measure", S, "Model Median Error %", 2))
    return [p1, p2, p3, p4]


def write_report() -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "definition.pbir").write_text(json.dumps(
        {"version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}}, indent=2))
    config = {"version": "5.59", "themeCollection": {}, "activeSectionIndex": 0,
              "defaultDrillFilterOtherVisuals": True,
              "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": 1}}
    report = {"config": json.dumps(config), "layoutOptimization": 0,
              "sections": [p.section() for p in build_pages()]}
    (REPORT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    measures = parse_measures(PBI / "measures.dax")
    write_model(measures)
    write_report()
    (PBI / f"{NAME}.pbip").write_text(json.dumps({
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}}, indent=2))
    print(f"{len(measures)} measures, {len(TABLES) + 1} tables -> {PBI / (NAME + '.pbip')}")


if __name__ == "__main__":
    main()
