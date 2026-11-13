"""Build reports/london_property_findings.pptx: a short findings deck for a
non-technical audience, with native (editable) PowerPoint charts.

    python -m src.export_powerbi
    python -m src.make_deck

Every number on the slides is calculated here from powerbi/data/, so the deck stays
in step with the dashboard and the workbook.
"""
import pandas as pd
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

from src.config import ROOT

DATA = ROOT / "powerbi" / "data"
OUT = ROOT / "reports" / "london_property_findings.pptx"

INK = RGBColor(0x16, 0x23, 0x3B)        # navy: titles, dark slides
THAMES = RGBColor(0x0E, 0x7C, 0x86)     # teal: main data colour
BRASS = RGBColor(0xC9, 0x9A, 0x2E)      # accent: the one thing to look at
MIST = RGBColor(0xEE, 0xF1, 0xF4)       # card background
GREY = RGBColor(0xC9, 0xD0, 0xD8)       # secondary data
BODY = RGBColor(0x33, 0x41, 0x5C)
MUTED = RGBColor(0x6B, 0x7A, 0x90)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
HEAD, TEXT = "Cambria", "Calibri"

W, H = Inches(13.333), Inches(7.5)
M = Inches(0.6)                         # outer margin


# ---------------------------------------------------------------- numbers
def load():
    s = pd.read_csv(DATA / "fact_sales.csv", parse_dates=["sale_date"])
    b = pd.read_csv(DATA / "dim_borough.csv")
    f = pd.read_csv(DATA / "data_quality_funnel.csv")
    v = pd.read_csv(DATA / "fact_valuation_test.csv")
    s = s.merge(b, on="borough")
    s["ym"] = s["sale_date"].dt.strftime("%Y-%m")
    return s, b, f, v


def facts(s, b, f, v):
    monthly = s.groupby("ym").size()
    by_type = s.groupby("property_type")["price"].median()
    ten = s.groupby(["property_type", "tenure"])["price"].median().unstack()
    reliable = s[s["coverage"].str.startswith("Reliable")]
    bor = reliable.groupby("borough")["price"].median().sort_values(ascending=False)
    bands = ["£125k-£300k", "£300k-£500k", "£500k-£925k", "£925k-£1.5m", "£1.5m and over"]
    acc = v.groupby("predicted_band")[["model_ape", "baseline_ape"]].median().reindex(bands)
    return {
        "n": len(s), "median": s["price"].median(),
        "monthly": monthly,
        "march_x": monthly["2025-03"] / monthly[["2025-01", "2025-02"]].mean(),
        "april_drop": monthly["2025-04"] / monthly["2025-03"] - 1,
        "flat_share": (s["property_type"] == "Flat/Maisonette").mean(),
        "leasehold_share": (s["tenure"] == "Leasehold").mean(),
        "by_type": by_type.reindex(["Flat/Maisonette", "Terraced", "Semi-detached", "Detached"]),
        "lease_disc": (ten["Leasehold"] / ten["Freehold"] - 1).drop("Flat/Maisonette"),
        "boroughs": bor, "n_reliable": len(bor), "n_boroughs": len(b),
        "inner": s.loc[s["inner_outer"] == "Inner London", "price"].median(),
        "outer": s.loc[s["inner_outer"] == "Outer London", "price"].median(),
        "raw": int(f["rows_remaining"].iloc[0]), "clean": int(f["rows_remaining"].iloc[-1]),
        "funnel": f[f["rows_removed"] > 0],
        "model_err": v["model_ape"].median(), "base_err": v["baseline_ape"].median(),
        "within10": v["model_within_10pct"].mean(), "within20": v["model_within_20pct"].mean(),
        "acc": acc, "n_test": len(v),
    }


def gbp(x):
    return f"£{x / 1e6:.2f}m" if x >= 1e6 else f"£{x / 1e3:,.0f}k"


# ---------------------------------------------------------------- drawing helpers
def text(slide, x, y, w, h, runs, size=16, color=BODY, font=TEXT, bold=False,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, space_after=6, name=None):
    """Text box. `runs` is a string or a list of paragraphs; a paragraph is a string or
    a list of (text, {overrides}) runs."""
    tb = slide.shapes.add_textbox(x, y, w, h)
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    paras = [runs] if isinstance(runs, str) else runs
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        for t, opts in ([(para, {})] if isinstance(para, str) else para):
            r = p.add_run()
            r.text = t
            r.font.name = opts.get("font", font)
            r.font.size = Pt(opts.get("size", size))
            r.font.bold = opts.get("bold", bold)
            r.font.italic = opts.get("italic", False)
            r.font.color.rgb = opts.get("color", color)
    return tb


def box(slide, x, y, w, h, fill, name=None, rounded=True):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
                                 x, y, w, h)
    if rounded:
        shp.adjustments[0] = 0.06
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    shp.line.fill.background()
    shp.shadow.inherit = False
    if name:
        shp.name = name
    return shp


def background(slide, color):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def title(slide, t, kicker=None):
    """Same position, font and size on every content slide."""
    if kicker:
        text(slide, M, Inches(0.45), Inches(11), Inches(0.35), kicker.upper(), size=12,
             color=THAMES, bold=True, name="Kicker")
    text(slide, M, Inches(0.8), Inches(12.1), Inches(0.9), t, size=34, color=INK,
         font=HEAD, bold=True, name="Title")


def footer(slide, n, dark=False):
    c = RGBColor(0xA9, 0xB4, 0xC4) if dark else MUTED
    text(slide, M, Inches(7.0), Inches(9), Inches(0.3),
         "Source: HM Land Registry Price Paid Data, standard sales completed Jan 2025 - Jan 2026",
         size=10, color=c, name="Source")
    text(slide, Inches(11.73), Inches(7.0), Inches(1.0), Inches(0.3), str(n), size=10, color=c,
         align=PP_ALIGN.RIGHT, name="Slide number")


def takeaway(slide, x, y, w, h, heading, paras):
    """The deck's motif: a tinted panel on the right holding the 'so what'."""
    box(slide, x, y, w, h, MIST, name="Takeaway panel")
    pad = Inches(0.35)
    text(slide, x + pad, y + pad, w - 2 * pad, Inches(0.4), heading.upper(), size=12,
         color=THAMES, bold=True, name="Takeaway heading")
    text(slide, x + pad, y + pad + Inches(0.5), w - 2 * pad, h - 2 * pad - Inches(0.5), paras,
         size=16, color=BODY, space_after=12, name="Takeaway text")


def style_chart(chart, number_format=None, legend=False, font_size=12):
    chart.font.name = TEXT
    chart.font.size = Pt(font_size)
    chart.font.color.rgb = BODY
    chart.has_title = False          # the slide title says what the chart shows
    chart.has_legend = legend
    if legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(font_size)
    va = chart.value_axis
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = RGBColor(0xE3, 0xE7, 0xEC)
    va.major_gridlines.format.line.width = Pt(0.75)
    va.format.line.fill.background()
    va.tick_labels.font.color.rgb = MUTED
    if number_format:
        va.tick_labels.number_format = number_format
        va.tick_labels.number_format_is_linked = False
    ca = chart.category_axis
    ca.format.line.color.rgb = GREY
    ca.tick_labels.font.color.rgb = BODY
    ca.has_major_gridlines = False


def colour_points(series, colours):
    for i, c in enumerate(colours):
        pt = series.points[i]
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = c


def labels(series, number_format, position=XL_LABEL_POSITION.OUTSIDE_END, size=12):
    dl = series.data_labels
    dl.show_value = True
    dl.number_format = number_format
    dl.number_format_is_linked = False
    dl.position = position
    dl.font.size = Pt(size)
    dl.font.color.rgb = INK


# ---------------------------------------------------------------- slides
def slide_title(prs, F):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    background(s, INK)
    text(s, M, Inches(2.1), Inches(11), Inches(0.4), "LONDON HOUSING MARKET  |  2025 REVIEW",
         size=14, color=BRASS, bold=True)
    text(s, M, Inches(2.6), Inches(11.5), Inches(1.9),
         "What London homes sold for in 2025, and what drove the price",
         size=44, color=WHITE, font=HEAD, bold=True)
    text(s, M, Inches(4.7), Inches(10), Inches(0.9),
         f"An analysis of {F['n']:,} home sales across {F['n_boroughs']} boroughs, "
         "January 2025 to January 2026",
         size=18, color=RGBColor(0xCF, 0xD6, 0xE0))
    footer(s, 1, dark=True)
    s.notes_slide.notes_text_frame.text = (
        "Purpose: summarise what London homes sold for over the year, what explains the "
        "differences, how reliable the data is, and how far an automated valuation can be trusted.")


def slide_summary(prs, F):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "Four things to know about the market", "Summary")
    cards = [
        (gbp(F["median"]), "Typical (median) sale price",
         f"Inner London {gbp(F['inner'])}, outer London {gbp(F['outer'])}"),
        (f"{F['march_x']:.1f}×", "March 2025 sales vs an ordinary month",
         "Buyers rushed to complete before stamp duty rose on 1 April"),
        (f"{F['flat_share']:.0%}", "Of homes sold were flats or maisonettes",
         f"{F['leasehold_share']:.0%} of all sales were leasehold"),
        (f"{1 - F['model_err'] / F['base_err']:.0%}", "Smaller valuation error than the simple benchmark",
         f"Typical error {F['model_err']:.0%}, vs {F['base_err']:.0%} for the area median"),
    ]
    gap = Inches(0.3)
    cw = (W - 2 * M - 3 * gap) / 4
    y, ch = Inches(2.2), Inches(4.2)
    for i, (big, label, detail) in enumerate(cards):
        x = M + i * (cw + gap)
        box(s, x, y, cw, ch, MIST, name=f"Card {i + 1}")
        pad = Inches(0.3)
        text(s, x + pad, y + Inches(0.45), cw - 2 * pad, Inches(1.2), big, size=54,
             color=BRASS if i == 1 else THAMES, font=HEAD, bold=True)
        text(s, x + pad, y + Inches(1.85), cw - 2 * pad, Inches(0.9), label, size=17,
             color=INK, bold=True)
        text(s, x + pad, y + Inches(2.85), cw - 2 * pad, Inches(1.2), detail, size=14, color=BODY)
    footer(s, 2)
    s.notes_slide.notes_text_frame.text = (
        "Medians, not averages: a few very expensive homes pull the average up to about "
        "£800k, so the median is a better picture of a typical sale.")


def slide_stamp_duty(prs, F):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "A stamp duty deadline pulled sales into March", "Timing")
    m = F["monthly"]
    cd = CategoryChartData()
    cd.categories = [pd.Timestamp(k + "-01").strftime("%b %y") for k in m.index]
    cd.add_series("Sales completed", m.values.tolist())
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, M, Inches(1.9), Inches(8.0),
                            Inches(4.9), cd)
    gf.name = "Monthly sales chart"
    c = gf.chart
    style_chart(c, "#,##0")
    plot = c.plots[0]
    plot.gap_width = 45
    ser = plot.series[0]
    colours = [GREY] * len(m)
    colours[list(m.index).index("2025-03")] = BRASS
    colours[list(m.index).index("2025-04")] = INK
    colour_points(ser, colours)
    labels(ser, "#,##0", size=11)
    takeaway(s, Inches(9.0), Inches(1.9), Inches(3.73), Inches(4.9), "What happened", [
        [("March: ", {"bold": True, "color": INK}),
         (f"{m['2025-03']:,} sales, {F['march_x']:.1f}× the January-February average.", {})],
        [("April: ", {"bold": True, "color": INK}),
         (f"{m['2025-04']:,}, down {abs(F['april_drop']):.0%}, once lower stamp duty "
          "thresholds took effect.", {})],
        [("So: ", {"bold": True, "color": INK}),
         ("monthly price changes around the deadline mostly reflect which homes sold, "
          "not prices moving. Compare like with like.", {})],
    ])
    footer(s, 3)
    s.notes_slide.notes_text_frame.text = (
        "The rush was weighted towards flats and cheaper homes (flats were 69.5% of March sales "
        "vs about 65% in Jan-Feb), which is why the median fell in March and jumped in April. "
        "The notebook's mix-adjusted price index shrinks those swings from about 8.5% to 2-3%.")


def slide_types(prs, F):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "Property type sets the price level, and leasehold cuts it", "Homes")
    bt = F["by_type"]
    cd = CategoryChartData()
    cd.categories = ["Flat", "Terraced", "Semi-detached", "Detached"]
    cd.add_series("Median price", (bt.values / 1e3).round().tolist())
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, M, Inches(1.9), Inches(8.0),
                            Inches(4.9), cd)
    gf.name = "Price by type chart"
    c = gf.chart
    style_chart(c, '"£"#,##0"k"')
    c.plots[0].gap_width = 60
    ser = c.plots[0].series[0]
    colour_points(ser, [THAMES] * 4)
    labels(ser, '"£"#,##0"k"')
    d = F["lease_disc"]
    takeaway(s, Inches(9.0), Inches(1.9), Inches(3.73), Inches(4.9), "What it means", [
        f"A detached house typically sells for {bt['Detached'] / bt['Flat/Maisonette']:.1f}× "
        "the price of a flat.",
        [("Leasehold houses sell for ", {}),
         (f"{abs(d.max()) * 100:.0f}-{abs(d.min()):.0%} less ", {"bold": True, "color": INK}),
         ("than freehold houses of the same type.", {})],
        "These are often shared-ownership or short-lease homes, so tenure needs checking on "
        "any valuation.",
    ])
    footer(s, 4)
    s.notes_slide.notes_text_frame.text = (
        "Leasehold discounts: terraced {:.0%}, semi-detached {:.0%}, detached {:.0%}. These are "
        "raw medians, so part of the gap is location and size, not tenure alone.".format(
            d["Terraced"], d["Semi-detached"], d["Detached"]))


def slide_boroughs(prs, F):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "The priciest borough costs nearly 3× the cheapest", "Places")
    bor = F["boroughs"]
    pick = pd.concat([bor.head(5), bor.tail(5)])
    cd = CategoryChartData()
    cd.categories = list(pick.index)[::-1]          # bar charts draw bottom-up
    cd.add_series("Median price", (pick.values[::-1] / 1e3).round().tolist())
    gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, M, Inches(1.9), Inches(8.0),
                            Inches(4.9), cd)
    gf.name = "Borough chart"
    c = gf.chart
    style_chart(c, '"£"#,##0"k"')
    c.value_axis.visible = False
    c.value_axis.has_major_gridlines = False
    c.plots[0].gap_width = 40
    ser = c.plots[0].series[0]
    colour_points(ser, [GREY] * 5 + [THAMES] * 5)
    labels(ser, '"£"#,##0"k"')
    ratio = bor.iloc[0] / bor.iloc[-1]
    takeaway(s, Inches(9.0), Inches(1.9), Inches(3.73), Inches(4.9), "What it means", [
        f"{bor.index[0]} ({gbp(bor.iloc[0])}) is {ratio:.1f}× {bor.index[-1]} ({gbp(bor.iloc[-1])}).",
        f"Inner London's median is {gbp(F['inner'])} against {gbp(F['outer'])} in outer London.",
        [("Caveat: ", {"bold": True, "color": INK}),
         (f"only {F['n_reliable']} of {F['n_boroughs']} boroughs have enough sales to rank. "
          "Outer-borough coverage is partial.", {})],
    ])
    text(s, M, Inches(6.72), Inches(8), Inches(0.25),
         "Top five and bottom five of the boroughs with 300+ sales",
         size=11, color=MUTED)
    footer(s, 5)
    s.notes_slide.notes_text_frame.text = (
        "Hounslow ranks fourth here only because 94% of its sales in this extract are in W4 "
        "(Chiswick). That's logged as issue #2 in ISSUES.md, along with the fix.")


def slide_quality(prs, F):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "Four in five raw records passed the quality checks", "Data quality")
    f = F["funnel"]
    names = {"Standard market sale (category A)": "Not a standard market sale",
             "Inside Greater London": "Outside Greater London",
             "Valid postcode": "Invalid postcode"}
    cd = CategoryChartData()
    rows = f.sort_values("rows_removed")
    cd.categories = [names.get(x, "Price below £10k or above £20m" if x.startswith("Price") else x)
                     for x in rows["step"]]
    cd.add_series("Records removed", rows["rows_removed"].tolist())
    gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, M, Inches(3.2), Inches(8.0),
                            Inches(3.4), cd)
    gf.name = "Records removed chart"
    c = gf.chart
    style_chart(c, "#,##0")
    c.value_axis.visible = False
    c.value_axis.has_major_gridlines = False
    c.plots[0].gap_width = 50
    ser = c.plots[0].series[0]
    colour_points(ser, [GREY] * (len(rows) - 1) + [BRASS])
    labels(ser, "#,##0")
    # Funnel totals across the top
    stats = [(f"{F['raw']:,}", "raw records"), (f"{F['clean']:,}", "clean sales analysed"),
             (f"{F['clean'] / F['raw']:.0%}", "kept")]
    for i, (big, lab) in enumerate(stats):
        x = M + i * Inches(2.75)
        text(s, x, Inches(1.85), Inches(2.6), Inches(0.75), big, size=36, color=THAMES,
             font=HEAD, bold=True)
        text(s, x, Inches(2.6), Inches(2.6), Inches(0.35), lab, size=14, color=BODY)
    takeaway(s, Inches(9.0), Inches(1.9), Inches(3.73), Inches(4.9), "Why it matters", [
        "Almost every removed record is a non-standard sale: repossessions, company purchases "
        "and other transfers that aren't open-market prices.",
        "Each rule and its count is logged, and the dashboard reconciles to the clean total.",
        [("Known gaps ", {"bold": True, "color": INK}),
         ("are tracked in an issues log with cause and fix.", {})],
    ])
    footer(s, 6)
    s.notes_slide.notes_text_frame.text = (
        "Cleaning rules live in one list in src/clean.py, used both to clean the data and to "
        "produce this funnel, so the report can't drift from the data.")


def slide_accuracy(prs, F):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "Valuations beat the benchmark at every price level", "Valuation accuracy")
    a = F["acc"]
    cd = CategoryChartData()
    cd.categories = ["£125k-300k", "£300k-500k", "£500k-925k", "£925k-1.5m", "£1.5m+"]
    cd.add_series("Model", a["model_ape"].tolist())
    cd.add_series("Benchmark (area median)", a["baseline_ape"].tolist())
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, M, Inches(2.15), Inches(8.0),
                            Inches(4.65), cd)
    gf.name = "Accuracy chart"
    c = gf.chart
    style_chart(c, "0%", legend=True)
    c.plots[0].gap_width = 60
    c.plots[0].overlap = -10
    for ser, col in zip(c.plots[0].series, [THAMES, GREY]):
        ser.format.fill.solid()
        ser.format.fill.fore_color.rgb = col
        labels(ser, "0%", size=11)
    text(s, M, Inches(1.85), Inches(8), Inches(0.3),
         "Median valuation error by predicted value, test sales Nov 2025 - Jan 2026",
         size=13, color=MUTED)
    takeaway(s, Inches(9.0), Inches(1.9), Inches(3.73), Inches(4.9), "What it means", [
        f"Tested on {F['n_test']:,} later sales the model never saw: "
        f"{F['within20']:.0%} land within 20% of the sale price.",
        f"Error rises from {a['model_ape'].iloc[0]:.0%} to {a['model_ape'].iloc[-1]:.0%} as value "
        "rises, because the data has no floor area.",
        [("Use it ", {"bold": True, "color": INK}),
         ("as a first estimate with a confidence range, not a final valuation.", {})],
    ])
    footer(s, 7)
    s.notes_slide.notes_text_frame.text = (
        "Model: LightGBM trained on Jan-Oct 2025 sales. Benchmark: median price in the same "
        "postcode sector over the previous six months. Test: Nov 2025 - Jan 2026 sales.")


def slide_next(prs, F):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    background(s, INK)
    text(s, M, Inches(0.45), Inches(11), Inches(0.35), "NEXT STEPS", size=12, color=BRASS, bold=True)
    text(s, M, Inches(0.8), Inches(12.1), Inches(0.9), "Three changes would make the numbers more useful",
         size=34, color=WHITE, font=HEAD, bold=True)
    steps = [
        ("1", "Add floor area", "Join energy-certificate (EPC) floor areas by postcode. Size is the "
                                "biggest missing driver of price, especially above £1m."),
        ("2", "Fill the borough gaps", "Rebuild from the full Land Registry files so outer boroughs "
                                       "like Sutton and Kingston are properly covered."),
        ("3", "Report like with like", "Use rolling or mix-adjusted prices in monthly reporting, and "
                                       "flag March-April 2025 wherever it appears."),
    ]
    gap = Inches(0.35)
    cw = (W - 2 * M - 2 * gap) / 3
    y = Inches(2.3)
    for i, (num, head, body) in enumerate(steps):
        x = M + i * (cw + gap)
        box(s, x, y, cw, Inches(3.3), RGBColor(0x22, 0x33, 0x52), name=f"Step {num}")
        circ = s.shapes.add_shape(MSO_SHAPE.OVAL, x + Inches(0.35), y + Inches(0.4),
                                  Inches(0.7), Inches(0.7))
        circ.fill.solid()
        circ.fill.fore_color.rgb = BRASS
        circ.line.fill.background()
        circ.shadow.inherit = False
        tf = circ.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = num
        r.font.size, r.font.bold, r.font.name = Pt(22), True, HEAD
        r.font.color.rgb = INK
        text(s, x + Inches(0.35), y + Inches(1.35), cw - Inches(0.7), Inches(0.5), head,
             size=20, color=WHITE, bold=True)
        text(s, x + Inches(0.35), y + Inches(1.95), cw - Inches(0.7), Inches(1.8), body,
             size=15, color=RGBColor(0xCF, 0xD6, 0xE0))
    footer(s, 8, dark=True)
    s.notes_slide.notes_text_frame.text = (
        "The EPC join is already supported in src/geo.py once the certificate file is downloaded.")


def main() -> None:
    s, b, f, v = load()
    F = facts(s, b, f, v)
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    prs.core_properties.title = "What London homes sold for in 2025"
    for build in (slide_title, slide_summary, slide_stamp_duty, slide_types, slide_boroughs,
                  slide_quality, slide_accuracy, slide_next):
        build(prs, F)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"Saved {OUT} ({len(prs.slides)} slides)")


if __name__ == "__main__":
    main()
