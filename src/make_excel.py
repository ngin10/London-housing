"""Build reports/london_property_summary.xlsx from the Power BI export.

Every summary figure is an Excel formula over the Sales and Valuations sheets, so the
workbook recalculates if the data changes. Medians use AGGREGATE(17, 6, ...), which
works in Excel 2010 and later without array entry.

    python -m src.export_powerbi
    python -m src.make_excel

openpyxl doesn't calculate formulas: open the file in Excel (and save) to see values.
"""
import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import ColorScaleRule, DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from src.config import ROOT

DATA = ROOT / "powerbi" / "data"
OUT = ROOT / "reports" / "london_property_summary.xlsx"

FONT = "Arial"
INK, TEAL, MUTED, HEAD_FILL, BAND = "16233B", "0E7C86", "5B6577", "E6F0F1", "F4F6F8"
GBP, PCT, INT = '"£"#,##0', "0.0%", "#,##0"
K_FMT = '"£"0,"k"'   # chart axes: £600k, independent of the PC's digit grouping

TYPES = ["Flat/Maisonette", "Terraced", "Semi-detached", "Detached"]


def font(**kw):
    return Font(name=FONT, **kw)


def title(ws, text, sub=None):
    ws["A1"] = text
    ws["A1"].font = font(size=16, bold=True, color=INK)
    if sub:
        ws["A2"] = sub
        ws["A2"].font = font(size=10, italic=True, color=MUTED)


def header(ws, row, labels, col=1):
    thin = Side(style="thin", color="C9D0D8")
    for i, label in enumerate(labels):
        c = ws.cell(row=row, column=col + i, value=label)
        c.font = font(bold=True, color=INK)
        c.fill = PatternFill("solid", fgColor=HEAD_FILL)
        c.alignment = Alignment(wrap_text=True, vertical="center")
        c.border = Border(bottom=thin)


def widths(ws, w):
    for i, x in enumerate(w, start=1):
        ws.column_dimensions[get_column_letter(i)].width = x


def body_font(ws):
    for row in ws.iter_rows():
        for c in row:
            if c.value is not None and c.font.name != FONT:
                c.font = font(bold=c.font.bold, italic=c.font.italic, color=c.font.color)


def tidy_chart(ch):
    ch.roundedCorners = False
    if ch.legend is not None:
        ch.legend.overlay = False
    if ch.title is not None:
        ch.title.overlay = False
    ch.x_axis.delete = False
    ch.y_axis.delete = False


# ---------------------------------------------------------------- data sheets
def sales_sheet(wb, sales, boroughs):
    ws = wb.create_sheet("Sales")
    df = sales.merge(boroughs[["borough", "inner_outer"]], on="borough", how="left")
    df["year_month"] = pd.to_datetime(df["sale_date"]).dt.strftime("%Y-%m")
    df["sdlt_period"] = (pd.to_datetime(df["sale_date"]) < "2025-04-01").map(
        {True: "Before 1 Apr 2025", False: "From 1 Apr 2025"})
    cols = ["transaction_id", "sale_date", "year_month", "price", "price_band", "borough",
            "inner_outer", "property_type", "tenure", "new_build", "sdlt_period"]
    df = df[cols]
    ws.append(cols)
    for r in df.itertuples(index=False):
        ws.append([r[0], pd.Timestamp(r[1]).to_pydatetime(), *r[2:]])
    n = len(df) + 1
    for row in ws.iter_rows(min_row=2, max_row=n, min_col=2, max_col=2):
        row[0].number_format = "dd/mm/yyyy"
    for row in ws.iter_rows(min_row=2, max_row=n, min_col=4, max_col=4):
        row[0].number_format = GBP
    tab = Table(displayName="SalesTable", ref=f"A1:{get_column_letter(len(cols))}{n}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(tab)
    ws.freeze_panes = "A2"
    widths(ws, [40, 12, 11, 12, 16, 24, 14, 17, 11, 11, 18])
    # Column ranges used by every summary formula
    return {c: f"Sales!${get_column_letter(i + 1)}$2:${get_column_letter(i + 1)}${n}"
            for i, c in enumerate(cols)}


def valuation_sheet(wb, val):
    ws = wb.create_sheet("Valuations")
    cols = ["transaction_id", "predicted_band", "model_ape", "baseline_ape", "model_within_10pct"]
    ws.append(cols)
    for r in val[cols].itertuples(index=False):
        ws.append(list(r))
    n = len(val) + 1
    for row in ws.iter_rows(min_row=2, max_row=n, min_col=3, max_col=4):
        for c in row:
            c.number_format = PCT
    tab = Table(displayName="ValuationTable", ref=f"A1:E{n}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(tab)
    ws.freeze_panes = "A2"
    widths(ws, [40, 16, 12, 13, 18])
    return {c: f"Valuations!${get_column_letter(i + 1)}$2:${get_column_letter(i + 1)}${n}"
            for i, c in enumerate(cols)}


def median_if(value_rng, *conds):
    """AGGREGATE(17,6,...) = QUARTILE.INC ignoring errors; quart 2 = median.
    Rows failing a condition divide by zero and are skipped."""
    filt = "".join(f"/({rng}={crit})" for rng, crit in conds)
    # The file format stores Excel 2010+ functions with an _xlfn. prefix (Excel hides it)
    return f"=_xlfn.AGGREGATE(17,6,{value_rng}{filt},2)"


# ---------------------------------------------------------------- summary sheets
def boroughs_sheet(wb, R, boroughs, sales):
    ws = wb.create_sheet("Boroughs")
    title(ws, "Median price by borough",
          "Sorted by median price. The last rows have fewer than 300 sales: this extract only "
          "partly covers them (ISSUES.md #2), so they are left out of the chart.")
    cols = ["Borough", "Inner / Outer", "Sales", "Median price", "Average price",
            "Leasehold share", "New-build share", "Coverage"]
    header(ws, 4, cols)
    # Reliable boroughs first (sorted by median), thin-coverage ones underneath,
    # so the chart can cover the reliable block only
    med = sales.groupby("borough")["price"].median().rename("median")
    b = boroughs.merge(med, left_on="borough", right_index=True)
    b["reliable"] = b["sales_count"] >= 300
    b = b.sort_values(["reliable", "median"], ascending=[False, False]).reset_index(drop=True)
    n_reliable = int(b["reliable"].sum())
    for i, row in b.iterrows():
        r = 5 + i
        ws.cell(r, 1, row["borough"])
        ws.cell(r, 2, row["inner_outer"])
        ws.cell(r, 3, f"=COUNTIFS({R['borough']},A{r})").number_format = INT
        ws.cell(r, 4, median_if(R["price"], (R["borough"], f"A{r}"))).number_format = GBP
        ws.cell(r, 5, f"=AVERAGEIFS({R['price']},{R['borough']},A{r})").number_format = GBP
        ws.cell(r, 6, f'=COUNTIFS({R["borough"]},A{r},{R["tenure"]},"Leasehold")/C{r}').number_format = PCT
        ws.cell(r, 7, f'=COUNTIFS({R["borough"]},A{r},{R["new_build"]},"New build")/C{r}').number_format = PCT
        ws.cell(r, 8, f'=IF(C{r}>=300,"Reliable",IF(C{r}>=100,"Thin","Too few"))')
    last = 4 + len(b)
    t = last + 1
    ws.cell(t, 1, "All London").font = font(bold=True)
    ws.cell(t, 3, f"=SUM(C5:C{last})").number_format = INT
    ws.cell(t, 4, f"=MEDIAN({R['price']})").number_format = GBP
    ws.cell(t, 5, f"=AVERAGE({R['price']})").number_format = GBP
    ws.cell(t, 6, f'=COUNTIFS({R["tenure"]},"Leasehold")/C{t}').number_format = PCT
    ws.cell(t, 7, f'=COUNTIFS({R["new_build"]},"New build")/C{t}').number_format = PCT
    for c in range(1, 9):
        ws.cell(t, c).font = font(bold=True)
    ws.conditional_formatting.add(f"D5:D{last}", DataBarRule(start_type="min", end_type="max", color="9CCBCF"))
    ws.conditional_formatting.add(f"C5:C{last}", ColorScaleRule(start_type="min", start_color="FDECEA",
                                                                end_type="percentile", end_value=50,
                                                                end_color="FFFFFF"))
    ws.freeze_panes = "B5"
    widths(ws, [26, 14, 10, 14, 14, 12, 12, 11])

    ch = BarChart()
    ch.type = "bar"
    ch.title = f"Median price, {n_reliable} boroughs with 300+ sales"
    ch.style = 2
    ch.add_data(Reference(ws, min_col=4, min_row=4, max_row=4 + n_reliable), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=5, max_row=4 + n_reliable))
    ch.x_axis.scaling.orientation = "maxMin"   # most expensive at the top
    ch.y_axis.crosses = "max"                  # keeps the value axis at the bottom
    ch.y_axis.numFmt = K_FMT
    ch.y_axis.majorGridlines = None
    ch.legend = None
    ch.series[0].graphicalProperties.solidFill = TEAL
    ch.height, ch.width = 14, 16
    tidy_chart(ch)
    ws.add_chart(ch, "J4")


def monthly_sheet(wb, R, sales):
    ws = wb.create_sheet("Monthly")
    title(ws, "Sales and median price by month",
          "Stamp duty thresholds fell on 1 April 2025. Buyers rushed to complete in March, "
          "then sales collapsed in April.")
    cols = ["Month", "Sales", "Change in sales vs previous month", "Median price",
            "Flat share", "Period"]
    header(ws, 4, cols)
    months = sorted(pd.to_datetime(sales["sale_date"]).dt.strftime("%Y-%m").unique())
    for i, m in enumerate(months):
        r = 5 + i
        ws.cell(r, 1, m)
        ws.cell(r, 2, f"=COUNTIFS({R['year_month']},A{r})").number_format = INT
        ws.cell(r, 3, "" if i == 0 else f"=B{r}/B{r - 1}-1").number_format = PCT
        ws.cell(r, 4, median_if(R["price"], (R["year_month"], f"A{r}"))).number_format = GBP
        ws.cell(r, 5, f'=COUNTIFS({R["year_month"]},A{r},{R["property_type"]},"Flat/Maisonette")/B{r}').number_format = PCT
        ws.cell(r, 6, f'=IF(A{r}<"2025-04","Before stamp duty change","After stamp duty change")')
    last = 4 + len(months)
    n = last + 2
    ws.cell(n, 1, "March 2025 sales vs Jan-Feb average").font = font(bold=True)
    ws.cell(n, 2, "=B7/AVERAGE(B5:B6)").number_format = '0.0"×"'
    ws.cell(n, 3, "Rows 5-7 are Jan, Feb and Mar 2025.").font = font(italic=True, color=MUTED)
    ws.freeze_panes = "B5"
    widths(ws, [11, 10, 16, 14, 11, 26])

    bars = BarChart()
    bars.title = "Sales per month (bars) and median price (line)"
    bars.add_data(Reference(ws, min_col=2, min_row=4, max_row=last), titles_from_data=True)
    bars.set_categories(Reference(ws, min_col=1, min_row=5, max_row=last))
    bars.y_axis.majorGridlines = None
    bars.series[0].graphicalProperties.solidFill = "9CCBCF"
    line = LineChart()
    line.add_data(Reference(ws, min_col=4, min_row=4, max_row=last), titles_from_data=True)
    line.y_axis.axId = 200
    line.y_axis.numFmt = K_FMT
    line.y_axis.crosses = "max"
    line.y_axis.majorGridlines = None
    line.series[0].smooth = False
    line.series[0].graphicalProperties.line.solidFill = INK
    line.series[0].graphicalProperties.line.width = 28000
    line.y_axis.delete = False
    bars += line
    bars.legend.position = "b"
    bars.height, bars.width = 9, 18
    tidy_chart(bars)
    ws.add_chart(bars, "H4")


def types_sheet(wb, R):
    ws = wb.create_sheet("Property types")
    title(ws, "Price by property type, tenure and new build",
          "Leasehold houses sell for much less than freehold ones: many are shared-ownership or "
          "short-lease homes.")
    header(ws, 4, ["Property type", "Sales", "Share of sales", "Median price",
                   "Median: freehold", "Median: leasehold", "Leasehold discount",
                   "Median: new build", "Median: existing", "New-build premium"])
    for i, t in enumerate(TYPES):
        r = 5 + i
        ws.cell(r, 1, t)
        ws.cell(r, 2, f"=COUNTIFS({R['property_type']},A{r})").number_format = INT
        ws.cell(r, 3, f"=B{r}/SUM($B$5:$B$8)").number_format = PCT
        ws.cell(r, 4, median_if(R["price"], (R["property_type"], f"A{r}"))).number_format = GBP
        for col, ten in [(5, '"Freehold"'), (6, '"Leasehold"')]:
            f = median_if(R["price"], (R["property_type"], f"A{r}"), (R["tenure"], ten))
            ws.cell(r, col, f'=IFERROR({f[1:]},"-")').number_format = GBP
        ws.cell(r, 7, f'=IFERROR(F{r}/E{r}-1,"-")').number_format = PCT
        for col, nb in [(8, '"New build"'), (9, '"Existing"')]:
            f = median_if(R["price"], (R["property_type"], f"A{r}"), (R["new_build"], nb))
            ws.cell(r, col, f'=IFERROR({f[1:]},"-")').number_format = GBP
        ws.cell(r, 10, f'=IFERROR(H{r}/I{r}-1,"-")').number_format = PCT
    ws.cell(10, 1, "A '-' means there are no sales in that group (for example, no new-build "
                   "detached houses).").font = font(italic=True, color=MUTED)
    widths(ws, [18, 10, 10, 13, 13, 13, 12, 13, 13, 12])

    ch = BarChart()
    ch.title = "Median price by property type"
    ch.add_data(Reference(ws, min_col=4, min_row=4, max_row=8), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=5, max_row=8))
    ch.y_axis.numFmt = K_FMT
    ch.y_axis.majorGridlines = None
    ch.legend = None
    ch.series[0].graphicalProperties.solidFill = TEAL
    ch.height, ch.width = 8, 14
    tidy_chart(ch)
    ws.add_chart(ch, "A12")


def quality_sheet(wb, R, funnel):
    ws = wb.create_sheet("Data quality")
    title(ws, "Data-quality funnel: rows kept by each cleaning rule",
          "Row counts come from src/clean.py cleaning_funnel(), run on data/raw/london_sales_final.csv.")
    header(ws, 4, ["Step", "Rule", "Rows remaining", "Rows removed", "Share of raw kept"])
    for i, row in funnel.iterrows():
        r = 5 + i
        ws.cell(r, 1, int(row["step_order"]))
        ws.cell(r, 2, row["step"])
        ws.cell(r, 3, int(row["rows_remaining"])).font = font(color="0000FF")  # input from Python
        ws.cell(r, 3).number_format = INT
        ws.cell(r, 4, 0 if i == 0 else f"=C{r - 1}-C{r}").number_format = INT
        ws.cell(r, 5, f"=C{r}/$C$5").number_format = PCT
    last = 4 + len(funnel)
    c = last + 2
    ws.cell(c, 2, "Check: clean rows equal rows on the Sales sheet").font = font(bold=True)
    ws.cell(c, 3, f'=IF(C{last}=COUNTA({R["transaction_id"]}),"OK","MISMATCH")')
    ws.cell(c + 1, 2, "Blue numbers are inputs exported from Python; black cells are formulas.").font = \
        font(italic=True, color=MUTED)
    ws.conditional_formatting.add(f"D6:D{last}", DataBarRule(start_type="num", start_value=0,
                                                            end_type="max", color="F4B6BE"))
    widths(ws, [7, 36, 15, 14, 16])


def accuracy_sheet(wb, V):
    ws = wb.create_sheet("Valuation accuracy")
    title(ws, "How accurate are the automated valuations?",
          "Model trained on Jan-Oct 2025 and tested on 10,023 sales from Nov 2025 to Jan 2026. "
          "Baseline = previous 6-month median price in the same postcode sector.")
    header(ws, 4, ["Predicted value band", "Valuations", "Model median error",
                   "Baseline median error", "Model within 10%"])
    bands = ["£125k-£300k", "£300k-£500k", "£500k-£925k", "£925k-£1.5m", "£1.5m and over"]
    for i, band in enumerate(bands):
        r = 5 + i
        ws.cell(r, 1, band)
        ws.cell(r, 2, f"=COUNTIFS({V['predicted_band']},A{r})").number_format = INT
        ws.cell(r, 3, median_if(V["model_ape"], (V["predicted_band"], f"A{r}"))).number_format = PCT
        ws.cell(r, 4, median_if(V["baseline_ape"], (V["predicted_band"], f"A{r}"))).number_format = PCT
        ws.cell(r, 5, f"=AVERAGEIFS({V['model_within_10pct']},{V['predicted_band']},A{r})").number_format = PCT
    t = 5 + len(bands)
    ws.cell(t, 1, "All valuations")
    ws.cell(t, 2, f"=SUM(B5:B{t - 1})").number_format = INT
    ws.cell(t, 3, f"=MEDIAN({V['model_ape']})").number_format = PCT
    ws.cell(t, 4, f"=MEDIAN({V['baseline_ape']})").number_format = PCT
    ws.cell(t, 5, f"=AVERAGE({V['model_within_10pct']})").number_format = PCT
    for c in range(1, 6):
        ws.cell(t, c).font = font(bold=True)
    ws.cell(t + 2, 1, "Error reduction vs baseline").font = font(bold=True)
    ws.cell(t + 2, 3, f"=1-C{t}/D{t}").number_format = PCT
    widths(ws, [22, 12, 15, 17, 15])

    ch = BarChart()
    ch.title = "Median valuation error by value band"
    ch.add_data(Reference(ws, min_col=3, max_col=4, min_row=4, max_row=t - 1), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=5, max_row=t - 1))
    ch.y_axis.numFmt = "0%"
    ch.y_axis.majorGridlines = None
    ch.series[0].graphicalProperties.solidFill = TEAL
    ch.series[1].graphicalProperties.solidFill = "C9D0D8"
    ch.legend.position = "b"
    ch.height, ch.width = 8, 15
    tidy_chart(ch)
    ws.add_chart(ch, "G4")


def readme_sheet(wb):
    ws = wb.active
    ws.title = "Read me"
    title(ws, "London home sales, Jan 2025 - Jan 2026: summary workbook")
    rows = [
        ("Source", "HM Land Registry Price Paid Data (standard sales, category A), 55,035 sales "
                   "completed 1 Jan 2025 - 30 Jan 2026. Contains HM Land Registry data © Crown "
                   "copyright 2026, Open Government Licence v3.0."),
        ("Built by", "src/make_excel.py, from the tables in powerbi/data/ (python -m src.export_powerbi)."),
        ("", ""),
        ("Sheet", "What it shows"),
        ("Boroughs", "Sales, median and average price, leasehold and new-build share, and data coverage per borough"),
        ("Monthly", "Sales and median price per month, including the stamp duty rush in March 2025"),
        ("Property types", "Medians by type, the leasehold discount and the new-build premium"),
        ("Data quality", "Rows kept and removed by each cleaning rule, with a reconciliation check"),
        ("Valuation accuracy", "Model vs baseline error by predicted value band"),
        ("Sales", "All 55,035 sales as an Excel table (SalesTable). Insert > PivotTable to explore it"),
        ("Valuations", "Holdout valuation errors (ValuationTable)"),
        ("", ""),
        ("How it works", "Every summary figure is a formula over the Sales or Valuations sheet "
                         "(COUNTIFS, AVERAGEIFS, and AGGREGATE(17,6,...) for medians). Blue text = "
                         "values typed in from Python; black = formulas."),
        ("Medians, not averages", "London prices are heavily skewed by a few very expensive homes, "
                                  "so medians describe a typical sale better than averages."),
    ]
    for i, (a, b) in enumerate(rows):
        r = 3 + i
        ws.cell(r, 1, a).font = font(bold=True, color=INK)
        ws.cell(r, 2, b).alignment = Alignment(wrap_text=True, vertical="top")
    header(ws, 6, ["Sheet", "What it shows"])
    widths(ws, [22, 100])


def main() -> None:
    sales = pd.read_csv(DATA / "fact_sales.csv")
    boroughs = pd.read_csv(DATA / "dim_borough.csv")
    funnel = pd.read_csv(DATA / "data_quality_funnel.csv")
    val = pd.read_csv(DATA / "fact_valuation_test.csv")

    wb = Workbook()
    readme_sheet(wb)
    R = sales_sheet(wb, sales, boroughs)
    V = valuation_sheet(wb, val)
    boroughs_sheet(wb, R, boroughs, sales)
    monthly_sheet(wb, R, sales)
    types_sheet(wb, R)
    quality_sheet(wb, R, funnel)
    accuracy_sheet(wb, V)
    # Summary sheets first, data sheets last
    wb.move_sheet("Sales", offset=len(wb.sheetnames))
    wb.move_sheet("Valuations", offset=len(wb.sheetnames))
    for ws in wb.worksheets:
        is_data = ws.title in ("Sales", "Valuations")
        if not is_data:   # data sheets take their font from the table style
            body_font(ws)
        ws.sheet_view.showGridLines = is_data

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
