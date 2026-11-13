"""London property market explorer.

Run locally (from the repo root):   streamlit run explorer/app.py
Data:                               data/raw/london_sales_final.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

import analysis as an

st.set_page_config(page_title="What a London home sells for", page_icon="🏠", layout="wide")

# ------------------------------------------------------------------ look and feel
INK, THAMES, MIST, BRASS, SIGNAL, SLATE = "#16233B", "#0E7C86", "#EEF1F4", "#C99A2E", "#D7263D", "#6B7A90"
TYPE_COLOURS = {"Flat": THAMES, "Terraced": BRASS, "Semi-detached": "#5B7DB1", "Detached": INK}
PRICE_SCALE = ["#E8F1F2", "#9CCBCF", "#3E9AA3", "#0E7C86", "#0B4F63", "#16233B"]

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;700;800&display=swap');
html, body, [class*="st-"], .stMarkdown, button, input, select, textarea { font-family: 'Public Sans', system-ui, sans-serif; }
h1, h2, h3 { font-family: 'Public Sans', system-ui, sans-serif; color: #16233B; letter-spacing: -0.01em; }
h1 { font-weight: 800; font-size: 2.6rem; line-height: 1.1; margin-bottom: 0.2rem; }
h2 { font-weight: 700; font-size: 1.45rem; margin-top: 1.6rem; }
h3 { font-weight: 700; font-size: 1.1rem; }
.block-container { padding-top: 2.2rem; max-width: 1180px; }
.lede { font-size: 1.15rem; line-height: 1.55; color: #33415C; max-width: 62ch; margin-bottom: 1.2rem; }
.note { font-size: 0.95rem; line-height: 1.6; color: #33415C; max-width: 75ch;
        border-left: 3px solid #0E7C86; padding: 0.2rem 0 0.2rem 0.9rem; margin: 0.4rem 0 1.4rem 0; }
.facts { display: flex; flex-wrap: wrap; gap: 0.4rem 2.2rem; font-size: 0.98rem; color: #33415C; margin: 0.6rem 0 1.4rem 0; }
.facts b { color: #16233B; font-size: 1.15rem; }
.finding { margin: 0 0 0.9rem 0; max-width: 78ch; line-height: 1.55; }
.finding b { color: #0E7C86; }
.estimate { font-size: 3rem; font-weight: 800; color: #16233B; line-height: 1; margin: 0.3rem 0; }
.range { font-size: 1.05rem; color: #33415C; }
a { color: #0E7C86; }
</style>
""", unsafe_allow_html=True)

pio.templates["london"] = go.layout.Template(layout=dict(
    font=dict(family="Public Sans, system-ui, sans-serif", color=INK, size=13),
    title=dict(font=dict(size=16, color=INK), x=0, xanchor="left"),
    colorway=[THAMES, BRASS, "#5B7DB1", INK, SIGNAL, SLATE],
    plot_bgcolor="white", paper_bgcolor="white",
    xaxis=dict(gridcolor="#E3E7EC", zerolinecolor="#C9D0D8", linecolor="#C9D0D8"),
    yaxis=dict(gridcolor="#E3E7EC", zerolinecolor="#C9D0D8", linecolor="#C9D0D8"),
    margin=dict(l=10, r=10, t=60, b=10), hoverlabel=dict(font_family="Public Sans"),
))
pio.templates.default = "london"


def gbp(v):
    return f"£{v/1e6:.2f}m" if v >= 1e6 else f"£{v/1e3:,.0f}k"


def note(text):
    st.markdown(f'<div class="note">{text}</div>', unsafe_allow_html=True)


def show(fig, height=None):
    if height:
        fig.update_layout(height=height)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})


# ------------------------------------------------------------------ data (cached)
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "london_sales_final.csv"


@st.cache_data(show_spinner="Loading and cleaning sales…")
def load(path_or_bytes):
    raw = pd.read_csv(path_or_bytes, low_memory=False)
    df, funnel = an.clean(raw)
    return raw, df, funnel


@st.cache_data(show_spinner="Fitting the hedonic models…")
def models(df):
    main, r2_main, resid = an.hedonic(df, *an.MAIN_SPEC, "pc_sector")
    flats = df[df["property_type"] == "F"]
    flat, r2_flat, _ = an.hedonic(flats, *an.FLAT_SPEC, "pc_sector")
    return main, r2_main, resid, flat, r2_flat


@st.cache_data(show_spinner="Testing the comparable-sales baseline…")
def accuracy_tables(df):
    return an.granularity_ladder(df), an.baseline_test(df)


@st.cache_data(show_spinner="Checking for spatial patterns in errors…")
def spatial(df):
    return an.spatial_check(df)


if DATA_PATH.exists():
    raw, df_all, funnel = load(DATA_PATH)
else:
    st.title("What a London home sells for")
    st.info("Add the data file to start: place london_sales_final.csv in data/raw/, or upload it here.")
    up = st.file_uploader("Upload london_sales_final.csv", type="csv")
    if up is None:
        st.stop()
    raw, df_all, funnel = load(up)

ATTRIBUTION = ("Contains HM Land Registry data © Crown copyright and database right 2026, licensed under the "
               "Open Government Licence v3.0. Postcode geography from postcodes.io (ONS). Crime data from data.police.uk.")


# ------------------------------------------------------------------ filters (explore pages only)
def filters():
    st.sidebar.markdown("### Filter the sales")
    boroughs = sorted(df_all["borough"].unique())
    pick_b = st.sidebar.multiselect("Boroughs", boroughs, placeholder="All boroughs")
    pick_t = st.sidebar.multiselect("Property types", an.TYPE_ORDER, placeholder="All types")
    lo, hi = st.sidebar.select_slider("Price range", options=[50_000, 250_000, 500_000, 750_000, 1_000_000,
                                      1_500_000, 2_000_000, 5_000_000, 100_000_000],
                                      value=(50_000, 100_000_000), format_func=lambda v: "No limit" if v == 100_000_000 else gbp(v))
    d = df_all
    if pick_b:
        d = d[d["borough"].isin(pick_b)]
    if pick_t:
        d = d[d["type_name"].isin(pick_t)]
    d = d[(d["price"] >= lo) & (d["price"] <= hi)]
    st.sidebar.caption(f"{len(d):,} of {len(df_all):,} sales selected")
    return d


def need(d, n=30):
    if len(d) < n:
        st.warning(f"Only {len(d)} sales match these filters. Widen the filters in the sidebar to see this view.")
        st.stop()


# ================================================================== pages
def page_overview():
    st.title("What a London home sells for, and why")
    st.markdown('<p class="lede">An analysis of 54,882 home sales in London postal districts, completed between '
                'January 2025 and January 2026. Each dot below is a neighbourhood of about 1,500 residents, '
                'coloured by its median sale price.</p>', unsafe_allow_html=True)

    g = df_all.groupby(["lsoa_code", "borough"]).agg(price=("price", "median"), n=("price", "size"),
                                                     lat=("latitude", "mean"), lon=("longitude", "mean")).reset_index()
    g = g[g["n"] >= 3]
    g["log_price"] = np.log10(g["price"])
    g["label"] = g["price"].map(gbp)
    ticks = [3e5, 5e5, 1e6, 2e6]
    fig = px.scatter_map(g, lat="lat", lon="lon", color="log_price", size="n", size_max=11,
                         color_continuous_scale=PRICE_SCALE, range_color=[np.log10(3e5), np.log10(2e6)],
                         hover_name="borough", hover_data={"label": True, "n": True, "lat": False, "lon": False, "log_price": False},
                         labels={"label": "Median price", "n": "Sales"}, zoom=9.6,
                         center={"lat": 51.505, "lon": -0.11}, map_style="carto-positron")
    fig.update_layout(height=620, margin=dict(l=0, r=0, t=0, b=0),
                      coloraxis_colorbar=dict(title="Median price", tickvals=np.log10(ticks),
                                              ticktext=[gbp(t) for t in ticks], thickness=12, len=0.6))
    show(fig)

    med = df_all["price"].median()
    st.markdown(f"""<div class="facts">
      <span><b>{gbp(med)}</b> median sale</span>
      <span><b>{(df_all['property_type'] == 'F').mean():.0%}</b> of sales are flats</span>
      <span><b>{gbp(df_all.loc[df_all['km_to_centre'] <= 2, 'price'].median())}</b> median within 2 km of the centre</span>
      <span><b>{gbp(df_all.loc[df_all['km_to_centre'] > 15, 'price'].median())}</b> beyond 15 km</span>
    </div>""", unsafe_allow_html=True)

    st.markdown("## What the data shows")
    findings = [
        ("Type and tenure set the baseline.", "A median flat sells for £490k and a detached house for £1.55m. Leasehold houses sell about 30% below freehold equivalents."),
        ("Location is worth as much as everything else combined.", "Type and tenure explain 21% of price variation; adding location step by step raises that to 66%."),
        ("The April 2025 stamp duty change pulled 10,053 sales into March.", "The raw median fell 8.5% then jumped 8.5%. Like-for-like prices moved only about 3% either way: most of the swing was which homes sold."),
        ("Buyers negotiate prices down to tax thresholds.", "When first-time buyer relief was capped at £500k instead of £625k, the cluster of sales just below the cap moved with it."),
        ("Crime lowers prices everywhere except the centre.", "Beyond 4 km from Charing Cross, the highest-crime areas sell 16–28% below the safest. In the centre, recorded crime tracks busy, desirable streets."),
        ("Some homes are much harder to value than others.", "A simple comparable-sales valuation misses by 11% in Bexley but 40% in Kensington and Chelsea, and the gap tracks how varied homes are on the same streets."),
    ]
    for head, body in findings:
        st.markdown(f'<p class="finding"><b>{head}</b> {body}</p>', unsafe_allow_html=True)
    st.caption(ATTRIBUTION)


def page_homes():
    d = filters(); need(d)
    st.title("Homes")
    st.markdown('<p class="lede">What kind of homes sell in London, and how type, tenure and new-build status shape price.</p>', unsafe_allow_html=True)

    c1, c2 = st.columns([1, 1.3])
    share = d["type_name"].value_counts(normalize=True).reindex(an.TYPE_ORDER).dropna().reset_index()
    share.columns = ["type", "share"]
    fig = px.bar(share, x="type", y="share", color="type", color_discrete_map=TYPE_COLOURS, text_auto=".0%",
                 title="Flats dominate London sales")
    fig.update_layout(showlegend=False, yaxis_tickformat=".0%", xaxis_title=None, yaxis_title="Share of sales")
    with c1:
        show(fig, 420)
    fig = px.box(d, x="type_name", y="price", color="type_name", color_discrete_map=TYPE_COLOURS, points=False,
                 category_orders={"type_name": an.TYPE_ORDER}, log_y=True, title="Each step up in type adds hundreds of thousands")
    fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Sale price (log scale)")
    with c2:
        show(fig, 420)
    note("Boxes show the middle half of sales for each type; whiskers extend to typical extremes. The ranges overlap "
         "heavily, so type alone does not decide price: a flat in Kensington can cost several times a terraced house in Bexley.")

    st.markdown("## Tenure and new builds")
    pv = d.pivot_table(index="type_name", columns="tenure_name", values="price", aggfunc="median").reindex(an.TYPE_ORDER)
    cnt = d.pivot_table(index="type_name", columns="tenure_name", values="price", aggfunc="size").reindex(an.TYPE_ORDER)
    text = pv.map(lambda v: gbp(v) if pd.notna(v) else "") + "<br>n=" + cnt.fillna(0).astype(int).astype(str)
    fig = go.Figure(go.Heatmap(z=pv.values, x=pv.columns, y=pv.index, text=text.values, texttemplate="%{text}",
                               colorscale=PRICE_SCALE, showscale=False))
    fig.update_layout(title="Leasehold houses sell well below freehold ones", yaxis_autorange="reversed")
    c1, c2 = st.columns(2)
    with c1:
        show(fig, 380)
    nb = d.groupby(["type_name", "new_build_name"])["price"].median().reset_index()
    fig = px.bar(nb, x="type_name", y="price", color="new_build_name", barmode="group",
                 category_orders={"type_name": an.TYPE_ORDER}, color_discrete_map={"Existing": "#AEB8C4", "New build": THAMES},
                 title="New builds carry a premium within each type")
    fig.update_layout(xaxis_title=None, yaxis_title="Median price", legend_title=None, yaxis_tickprefix="£", yaxis_tickformat=",.0f")
    with c2:
        show(fig, 380)
    note("99% of flats are leasehold and 95% of houses are freehold, so tenure mostly separates flats from houses. "
         "The exceptions carry the signal: leasehold houses are often former council or shared-ownership homes. "
         "New builds are 5% of sales, almost all flats, and concentrated in east London.")


def page_places():
    d = filters(); need(d)
    st.title("Places")
    st.markdown('<p class="lede">How price changes across boroughs and with distance from central London.</p>', unsafe_allow_html=True)

    b = d.groupby("borough")["price"].agg(["median", "size"]).sort_values("median").reset_index()
    b["label"] = b["median"].map(gbp) + "  (n=" + b["size"].map("{:,}".format) + ")"
    fig = px.bar(b, x="median", y="borough", orientation="h", text="label", color="median",
                 color_continuous_scale=PRICE_SCALE, title="Median sale price by borough")
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(coloraxis_showscale=False, xaxis_title="Median price", yaxis_title=None,
                      xaxis_range=[0, b["median"].max() * 1.35], xaxis_tickprefix="£", xaxis_tickformat=",.0f")
    show(fig, max(380, 26 * len(b) + 80))
    note("Borough medians mix property types, so part of a prime borough's premium is that it sells more large homes. "
         "Compare boroughs within one property type using the sidebar filter for a like-for-like view.")

    st.markdown("## Distance from the centre")
    d2 = d.assign(km=pd.cut(d["km_to_centre"], np.arange(0, 21, 1)))
    g = d2.groupby(["km", "type_name"], observed=True)["price"].agg(["median", "size"]).reset_index()
    g = g[g["size"] >= 30]
    g["km_mid"] = g["km"].apply(lambda i: i.mid)
    fig = px.line(g, x="km_mid", y="median", color="type_name", markers=True, log_y=True,
                  color_discrete_map=TYPE_COLOURS, category_orders={"type_name": an.TYPE_ORDER},
                  title="Prices fall steadily with every kilometre from Charing Cross")
    fig.update_layout(xaxis_title="Distance from Charing Cross (km)", yaxis_title="Median price (log scale)", legend_title=None)
    show(fig, 440)
    note("The gradient is steepest for flats, whose median roughly halves from the centre to beyond 10 km. "
         "Direction matters too: at the same distance, west London costs far more than east London.")

    part = d.groupby("london_part")["price"].agg(["median", "size"]).sort_values("median").reset_index()
    fig = px.bar(part, x="london_part", y="median", text=part["median"].map(gbp), color_discrete_sequence=[THAMES],
                 title="West and central postcodes are the most expensive")
    fig.update_layout(xaxis_title=None, yaxis_title="Median price", yaxis_tickprefix="£", yaxis_tickformat=",.0f")
    show(fig, 380)


def page_timing():
    d = filters(); need(d)
    st.title("Timing and tax")
    st.markdown('<p class="lede">On 1 April 2025 stamp duty thresholds fell. The rush to complete before the deadline '
                'distorted both volumes and the mix of homes sold.</p>', unsafe_allow_html=True)

    m = d.groupby("month").agg(sales=("price", "size"), median=("price", "median"),
                               cheap=("price", lambda s: (s < 500_000).mean()),
                               flats=("property_type", lambda s: (s == "F").mean())).reset_index()
    fig = go.Figure()
    fig.add_bar(x=m["month"], y=m["sales"], name="Completed sales",
                marker_color=[SIGNAL if x == "2025-03" else "#B9C6D3" for x in m["month"]])
    fig.add_scatter(x=m["month"], y=m["median"], name="Median price", yaxis="y2", mode="lines+markers", line_color=INK)
    fig.update_layout(title="Sales spiked in March 2025, then collapsed in April",
                      yaxis=dict(title="Completed sales"), yaxis2=dict(title="Median price", overlaying="y", side="right",
                      tickprefix="£", tickformat=",.0f", showgrid=False), legend=dict(orientation="h", y=1.08, x=0))
    show(fig, 440)

    fig = go.Figure()
    fig.add_scatter(x=m["month"], y=m["cheap"], name="Sales under £500k", mode="lines+markers", line_color=SIGNAL)
    fig.add_scatter(x=m["month"], y=m["flats"], name="Flats", mode="lines+markers", line_color=THAMES)
    fig.update_layout(title="Cheaper homes were pulled forward into March", yaxis_tickformat=".0%",
                      yaxis_title="Share of the month's sales", legend=dict(orientation="h", y=1.08, x=0))
    show(fig, 380)
    note("The tax change hit cheaper homes and first-time buyers hardest, so those sales moved earliest. "
         "March's lower median and April's jump are changes in <i>which</i> homes sold, not in what homes were worth. "
         "The <b>Model checks</b> page shows a like-for-like index that removes this effect.")

    st.markdown("## Prices bunch below tax thresholds")
    post = d["date"] >= "2025-04-01"
    bins = np.arange(400_000, 700_001, 5_000)
    fig = go.Figure()
    for mask, label, colour in [(~post, "Jan–Mar 2025 (first-time buyer relief up to £625k)", BRASS),
                                (post, "From April 2025 (relief up to £500k)", THAMES)]:
        if mask.sum() == 0:
            continue
        c, e = np.histogram(d.loc[mask, "price"] - 1, bins=bins)
        fig.add_scatter(x=e[:-1] + 2_500, y=c / mask.sum(), mode="lines", line_shape="hvh", name=label, line_color=colour)
    for t in (500_000, 625_000):
        fig.add_vline(x=t, line_dash="dot", line_color=INK, annotation_text=gbp(t), annotation_position="top")
    fig.update_layout(title="The spike below the relief cap moved when the cap changed", yaxis_tickformat=".1%",
                      yaxis_title="Share of period's sales per £5k", xaxis_tickprefix="£", xaxis_tickformat=",.0f",
                      legend=dict(orientation="h", y=-0.2, x=0))
    show(fig, 440)
    note("Paying £1 over the cap loses the whole first-time buyer relief, worth £10,000 at £500k. "
         "Buyers and sellers settle just below it. 75% of all sales are agreed at an exact multiple of £5,000.")

    wd = d["weekday"].value_counts(normalize=True).reindex(
        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]).fillna(0).reset_index()
    wd.columns = ["day", "share"]
    fig = px.bar(wd, x="day", y="share", text_auto=".0%", title="Most homes change hands on a Friday")
    fig.update_traces(marker_color=[SIGNAL if d_ == "Friday" else "#B9C6D3" for d_ in wd["day"]])
    fig.update_layout(yaxis_tickformat=".0%", xaxis_title=None, yaxis_title="Share of completions", showlegend=False)
    show(fig, 340)


def page_address():
    d = filters(); need(d)
    st.title("Clues in the address")
    st.markdown('<p class="lede">The address text hints at building age, construction and estate status, '
                'details not recorded anywhere else in the data.</p>', unsafe_allow_html=True)

    s = d.groupby("street_type")["price"].agg(["median", "size"]).sort_values("median").reset_index()
    s = s[s["size"] >= 20]
    fig = px.bar(s, x="median", y="street_type", orientation="h", text=s["median"].map(gbp),
                 color="median", color_continuous_scale=PRICE_SCALE, title="Median price by street name ending")
    fig.update_layout(coloraxis_showscale=False, yaxis_title=None, xaxis_title="Median price",
                      xaxis_tickprefix="£", xaxis_tickformat=",.0f", xaxis_range=[0, s["median"].max() * 1.2])
    show(fig, max(360, 26 * len(s) + 80))
    note("Mews, squares and gardens are typical of Georgian and Victorian inner London; closes and ways of post-war estates. "
         "Careful: within the same postcode sector, mews homes actually sell <i>below</i> main-road homes "
         "(see <b>Model checks</b>), because mews houses are small converted stables on expensive streets.")

    fl = d[d["property_type"] == "F"]
    if len(fl) >= 30:
        st.markdown("## Flats")
        c1, c2 = st.columns(2)
        for col, field, title in [(c1, "building_type", "Price by building name"), (c2, "floor_level", "Price by floor in the address")]:
            t = fl.groupby(field)["price"].agg(["median", "size"]).sort_values("median").reset_index()
            t = t[t["size"] >= 15]
            fig = px.bar(t, x="median", y=field, orientation="h", text=t["median"].map(gbp) + " (n=" + t["size"].astype(str) + ")",
                         color_discrete_sequence=[THAMES], title=title)
            fig.update_layout(yaxis_title=None, xaxis_title="Median price", xaxis_tickprefix="£", xaxis_tickformat=",.0f",
                              xaxis_range=[0, t["median"].max() * 1.45])
            with col:
                show(fig, 440)
        note("Flats in buildings named “Court” or “House” are often post-war or former council blocks and sell for less, "
             "even against flats on the same streets. Floor level is only written in about 5% of addresses; where it is, "
             "top floors and penthouses carry clear premiums.")


def page_crime():
    d = filters(); need(d, 200)
    st.title("Crime")
    st.markdown('<p class="lede">Recorded crime in each home’s neighbourhood (LSOA), January 2025 to January 2026, '
                'and how it relates to price once centrality is taken into account.</p>', unsafe_allow_html=True)

    d = d.assign(decile=pd.qcut(d["crimes"].rank(method="first"), 10, labels=False) + 1)
    g = d.groupby("decile").agg(price=("price", "median"), km=("km_to_centre", "median")).reset_index()
    fig = go.Figure()
    fig.add_scatter(x=g["decile"], y=g["price"], name="Median price", mode="lines+markers", line_color=SIGNAL)
    fig.add_scatter(x=g["decile"], y=g["km"], name="Median km to centre", yaxis="y2", mode="lines+markers",
                    line=dict(color=THAMES, dash="dash"))
    fig.update_layout(title="The highest-crime areas are also the most central",
                      xaxis_title="Crime decile (1 = lowest)", yaxis=dict(title="Median price", tickprefix="£", tickformat=",.0f"),
                      yaxis2=dict(title="km to centre", overlaying="y", side="right", showgrid=False),
                      legend=dict(orientation="h", y=1.08, x=0))
    show(fig, 420)

    d = d.assign(band=pd.cut(d["km_to_centre"], [0, 4, 8, 12, 25], labels=["0–4 km", "4–8 km", "8–12 km", "12+ km"]),
                 cq=pd.qcut(d["crimes"].rank(method="first"), 4, labels=["Lowest", "Lower-mid", "Upper-mid", "Highest"]))
    pv = d.pivot_table(index="band", columns="cq", values="price", aggfunc="median", observed=True)
    rel = pv.div(pv["Lowest"], axis=0) - 1
    fig = go.Figure(go.Heatmap(z=rel.values * 100, x=rel.columns, y=rel.index, zmid=0, colorscale="RdBu",
                               text=rel.map(lambda v: f"{v:+.0%}").values, texttemplate="%{text}",
                               colorbar=dict(title="% vs lowest", thickness=12)))
    fig.update_layout(title="Holding distance constant, crime lowers prices outside the centre",
                      xaxis_title="Crime quartile", yaxis_title="Distance from centre", yaxis_autorange="reversed")
    show(fig, 400)
    note("Recorded crime counts incidents, and incidents follow footfall. Central London attracts huge numbers of visitors, "
         "so some of its most valuable streets record the most crime. Outside the centre, the expected pattern appears: "
         "the highest-crime areas sell well below the safest at the same distance.")


def page_value():
    st.title("Value a home")
    st.markdown('<p class="lede">An estimate from comparable sales: the same property type in the smallest nearby area '
                'with at least five sales, adjusted to the latest month with the like-for-like price index.</p>',
                unsafe_allow_html=True)
    main, *_ = models(df_all)
    index = an.price_index(main)
    nb_prem = main.loc[(main["variable"] == "new_build_name") & (main["level"] == "New build"), "pct"].iloc[0]
    _, test = accuracy_tables(df_all)
    borough_err = test.groupby("borough")["ape"].median()

    c1, c2, c3 = st.columns([1.2, 1, 1])
    postcode = c1.text_input("Postcode", value="SE15 4QF", help="Any London postcode in E, EC, N, NW, SE, SW, W or WC")
    ptype = c2.selectbox("Property type", an.TYPE_ORDER)
    newb = c3.toggle("New build", value=False)

    res = an.value_home(df_all, index, postcode, ptype, nb_prem if newb else None)
    if res is None:
        st.warning("There are not enough comparable sales for this postcode and property type. "
                   "Check the postcode, or try a different property type.")
        return
    err = borough_err.get(res["borough"], test["ape"].median())
    confidence = "High" if err < 0.15 else "Medium" if err < 0.25 else "Low"
    st.markdown(f'<div class="estimate">{gbp(res["estimate"])}</div>'
                f'<div class="range">Middle half of comparable sales: {gbp(res["low"])} to {gbp(res["high"])}</div>',
                unsafe_allow_html=True)
    st.markdown(f"""<div class="facts">
      <span><b>{res['n']}</b> comparable sales</span>
      <span>from the same <b>{res['level']}</b></span>
      <span>typical error in {res['borough']}: <b>±{err:.0%}</b></span>
      <span>confidence: <b>{confidence}</b></span>
    </div>""", unsafe_allow_html=True)
    if newb:
        st.caption(f"Includes the estimated new-build premium of {nb_prem:+.0%} (same type, same postcode sector).")
    note("This is the baseline method from the analysis, not a full valuation. It knows type, location and month, "
         "but not size, condition or outlook, which is why ranges in prime areas are wide.")

    comps = res["comps"][["date", "address", "postcode", "price", "tenure_name", "new_build_name"]].head(15).copy()
    comps["date"] = comps["date"].dt.strftime("%d %b %Y")
    comps["price"] = comps["price"].map(lambda v: f"£{v:,.0f}")
    comps.columns = ["Completed", "Address", "Postcode", "Price", "Tenure", "Build"]
    st.markdown("### Most recent comparable sales")
    st.dataframe(comps, hide_index=True, width="stretch")


def page_accuracy():
    st.title("How accurate is it?")
    st.markdown('<p class="lede">The comparable-sales method is trained on January–October 2025 and tested on '
                'November 2025–January 2026 sales it has never seen. This is the benchmark any machine-learning model must beat.</p>',
                unsafe_allow_html=True)
    ladder, test = accuracy_tables(df_all)
    c1, c2 = st.columns(2)
    fig = px.bar(ladder, x="level", y="R² in-sample", text_auto=".0%", color_discrete_sequence=[THAMES],
                 title="Share of price variation explained")
    fig.update_layout(yaxis_tickformat=".0%", xaxis_title=None, yaxis_title=None, yaxis_range=[0, 0.8])
    with c1:
        show(fig, 400)
    long = ladder.melt(id_vars="level", value_vars=["MdAPE", "Within ±10%"])
    fig = px.bar(long, x="level", y="value", color="variable", barmode="group", text_auto=".0%",
                 color_discrete_map={"MdAPE": SIGNAL, "Within ±10%": THAMES}, title="Error on unseen sales")
    fig.update_layout(yaxis_tickformat=".0%", xaxis_title=None, yaxis_title=None, legend_title=None,
                      legend=dict(orientation="h", y=1.1, x=0))
    with c2:
        show(fig, 400)
    note("Finer location keeps helping down to the LSOA. The best baseline has a median error of 20%, with 28% of "
         "estimates within ±10% of the sale price. The remaining gap is mostly home size and condition, which the data lacks.")

    st.markdown("## Where valuations are hardest")
    main, r2_main, resid, *_ = models(df_all)
    by_b = pd.DataFrame({"MdAPE": test.groupby("borough")["ape"].median(),
                         "dispersion": df_all.assign(r=resid).groupby("borough")["r"].std(),
                         "median_price": df_all.groupby("borough")["price"].median()}).dropna().reset_index()
    r = np.corrcoef(by_b["dispersion"], by_b["MdAPE"])[0, 1]
    by_b["price_label"] = by_b["median_price"].map(gbp)
    fig = px.scatter(by_b, x="dispersion", y="MdAPE", hover_name="borough", trendline="ols",
                     color="median_price", color_continuous_scale=PRICE_SCALE,
                     hover_data={"price_label": True, "median_price": False},
                     title=f"Boroughs with more varied homes are harder to value (r = {r:.2f})")
    fig.update_traces(marker=dict(size=11, line=dict(width=0.5, color="white")), selector=dict(mode="markers"))
    fig.update_layout(xaxis_title="Price dispersion within postcode sectors", yaxis_title="Median error",
                      yaxis_tickformat=".0%", coloraxis_colorbar=dict(title="Median price", tickprefix="£"))
    show(fig, 480)

    bands = [0, 300e3, 500e3, 750e3, 1e6, 2e6, np.inf]
    labels = ["<£300k", "£300–500k", "£500–750k", "£750k–1m", "£1–2m", "£2m+"]
    t = test.assign(actual=pd.cut(test["price"], bands, labels=labels), predicted=pd.cut(test["pred_price"], bands, labels=labels))
    a = t.groupby("actual", observed=True)["ape"].median().rename("By actual price")
    p = t.groupby("predicted", observed=True)["ape"].median().rename("By predicted value")
    seg = pd.concat([a, p], axis=1).reset_index(names="band").melt(id_vars="band")
    fig = px.bar(seg, x="band", y="value", color="variable", barmode="group", text_auto=".0%",
                 color_discrete_map={"By actual price": "#B9C6D3", "By predicted value": THAMES},
                 title="Report accuracy by predicted value, not actual price")
    fig.update_layout(yaxis_tickformat=".0%", xaxis_title=None, yaxis_title="Median error", legend_title=None,
                      legend=dict(orientation="h", y=1.1, x=0))
    show(fig, 420)
    note("Grouping by actual price makes cheap sales look terrible, because it selects sales that ended up unusually cheap, "
         "which are exactly the ones the method missed. Only the predicted value is known when valuing, so that is the honest view: "
         "error rises from about 16% under £500k to 35% above £2m.")


def page_models():
    st.title("Model checks")
    st.markdown('<p class="lede">Comparing like with like: each estimate below compares homes only with others in the '
                'same postcode sector, so location cannot explain the difference.</p>', unsafe_allow_html=True)
    main, r2_main, resid, flat, r2_flat = models(df_all)

    def forest(t, title, order=None):
        t = t.copy()
        t = t.set_index("level").loc[order].reset_index() if order else t.sort_values("pct")
        t["sig"] = np.where((t["lo"] > 0) | (t["hi"] < 0), "Clear difference", "Not clearly different from zero")
        fig = px.scatter(t, x="pct", y="level", color="sig", error_x=t["hi"] - t["pct"], error_x_minus=t["pct"] - t["lo"],
                         color_discrete_map={"Clear difference": THAMES, "Not clearly different from zero": "#B9C6D3"},
                         title=title, hover_data={"pct": ":+.1%", "lo": ":+.1%", "hi": ":+.1%", "sig": False})
        fig.add_vline(x=0, line_color=INK, line_width=1)
        fig.update_traces(marker_size=10)
        fig.update_yaxes(categoryorder="array", categoryarray=list(t["level"]))
        fig.update_layout(xaxis_tickformat="+.0%", xaxis_title="Price difference (95% interval)", yaxis_title=None,
                          legend_title=None, legend=dict(orientation="h", y=-0.15, x=0))
        return fig

    c1, c2 = st.columns(2)
    with c1:
        show(forest(main[main["variable"].isin(["type_tenure", "new_build_name"])],
                    "Versus an existing leasehold flat"), 460)
    with c2:
        show(forest(main[main["variable"] == "street_type"], "Street ending, versus “Road”"), 460)
    note("A freehold terraced house sells for about twice a leasehold flat on the same streets. New builds sell about 46% "
         "above existing homes of the same type nearby. Mews homes sell about 12% <i>below</i> main-road homes once location is fixed, "
         "the opposite of the raw ranking.")

    c1, c2 = st.columns(2)
    with c1:
        show(forest(flat[flat["variable"] == "floor_level"], "Flats: floor, versus floor not stated"), 420)
    with c2:
        show(forest(flat[flat["variable"] == "building_type"], "Flats: building name, versus a numbered building"), 420)

    st.markdown("## A like-for-like price index")
    idx = an.price_index(main)
    raw_m = df_all.groupby("month")["price"].median()
    raw_idx = (raw_m / raw_m.iloc[0] - 1).reset_index(name="raw")
    fig = go.Figure()
    fig.add_scatter(x=idx["month"], y=idx["hi"], mode="lines", line_width=0, showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=idx["month"], y=idx["lo"], mode="lines", line_width=0, fill="tonexty",
                    fillcolor="rgba(14,124,134,0.15)", name="95% interval", hoverinfo="skip")
    fig.add_scatter(x=idx["month"], y=idx["pct"], mode="lines+markers", name="Like-for-like index", line_color=THAMES)
    fig.add_scatter(x=raw_idx["month"], y=raw_idx["raw"], mode="lines+markers", name="Raw median", line_color=BRASS)
    fig.update_layout(title="Most of the stamp duty swing disappears once mix is removed", yaxis_tickformat="+.0%",
                      yaxis_title="Change since January 2025", legend=dict(orientation="h", y=1.08, x=0))
    show(fig, 420)

    st.markdown("## Do errors cluster in space?")
    mi, maps = spatial(df_all)
    c1, c2 = st.columns([1, 1.6])
    fig = px.bar(mi, x="controls", y="Moran's I", text_auto=".2f", color_discrete_sequence=[THAMES],
                 title="Spatial clustering of errors")
    fig.update_layout(xaxis_title="Location controls in the model", yaxis_range=[0, 0.85])
    with c1:
        show(fig, 420)
    choice = c2.radio("Show errors for a model with", ["No location", "Postcode sector"], horizontal=True)
    m = maps[choice]
    fig = px.scatter_map(m, lat="lat", lon="lon", color="r", color_continuous_scale="RdBu_r", range_color=[-0.6, 0.6],
                         zoom=9.2, center={"lat": 51.505, "lon": -0.11}, map_style="carto-positron",
                         hover_data={"r": ":.2f", "lat": False, "lon": False})
    fig.update_traces(marker_size=6)
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0),
                      coloraxis_colorbar=dict(title="Error<br>(log)", thickness=10))
    with c2:
        show(fig)
    note("Red areas sell above what the model expects, blue below. Without location, whole regions are mis-valued together "
         "(Moran's I 0.74). For a lender, that is concentration risk: the same error repeated across many loans. "
         "Postcode-sector controls remove the pattern (0.03).")

    st.markdown("## Unusual sales")
    sd = resid.std()
    flag = resid.abs() > 3 * sd
    out = df_all.loc[flag, ["date", "address", "borough", "type_name", "price"]].assign(
        expected=lambda x: x["price"] / np.exp(resid[flag]), ratio=np.exp(resid[flag]))
    out = out.sort_values("ratio")
    st.markdown(f"{flag.sum():,} sales ({flag.mean():.1%}) sit more than three standard deviations from their expected price. "
                "Most are partial interests, sales between connected parties or several units sold together; they are the "
                "first records to exclude from a model's training data.")
    show_df = pd.concat([out.head(8), out.tail(8)]).copy()
    show_df["date"] = show_df["date"].dt.strftime("%d %b %Y")
    show_df["price"] = show_df["price"].map(lambda v: f"£{v:,.0f}")
    show_df["expected"] = show_df["expected"].map(lambda v: f"£{v:,.0f}")
    show_df["ratio"] = show_df["ratio"].map(lambda v: f"{v:.2f}×")
    show_df.columns = ["Completed", "Address", "Borough", "Type", "Price", "Expected", "Price ÷ expected"]
    st.dataframe(show_df, hide_index=True, width="stretch")


def page_data():
    st.title("About the data")
    st.markdown('<p class="lede">Where the data comes from, how it was cleaned, and what it cannot tell you.</p>', unsafe_allow_html=True)
    f = funnel.copy()
    f["removed"] = (-f["rows"].diff()).fillna(0).astype(int)
    f["label"] = f["rows"].map("{:,}".format) + np.where(f["removed"] > 0, "  (−" + f["removed"].map("{:,}".format) + ")", "")
    fig = px.bar(f.iloc[::-1], x="rows", y="step", orientation="h", text="label", color_discrete_sequence=[THAMES],
                 title="Rows kept at each cleaning step")
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(xaxis_title=None, yaxis_title=None, xaxis_range=[0, f["rows"].max() * 1.3])
    show(fig, 420)
    note("Most removals are Land Registry category B transactions: repossessions, buy-to-let portfolio purchases and transfers "
         "to companies. The largest was a £793m sale of an entire Westminster building.")

    miss = raw.isna().mean().sort_values(ascending=False)
    miss = miss[miss > 0].reset_index()
    miss.columns = ["column", "missing"]
    fig = px.bar(miss, x="missing", y="column", orientation="h", text_auto=".1%", color_discrete_sequence=[SLATE],
                 title="Missing values in the raw extract")
    fig.update_layout(xaxis_tickformat=".0%", yaxis_title=None, xaxis_title=None, yaxis_autorange="reversed")
    show(fig, 340)
    note("<b>saon</b> (the flat number) is empty for whole houses, so the gap is information, not an error. "
         "<b>locality</b> is an optional address line rarely used in London and is dropped.")

    st.markdown("## Sources")
    st.markdown("""
- **HM Land Registry Price Paid Data**: every residential sale in England and Wales.
- **postcodes.io**: postcode coordinates and neighbourhood (LSOA) codes, from ONS data.
- **data.police.uk**: street-level crime for the Metropolitan Police and City of London Police.
""")
    st.markdown("## Limitations")
    st.markdown("""
- **No floor area or bedroom count.** Size is the biggest driver of value that this data lacks.
- **London postal districts only.** Outer boroughs with other postcodes (Croydon, Bromley, Harrow) are thin or missing.
- **One year of data** that includes a tax change, so seasonal patterns cannot be separated from trend.
- **Completion prices lag agreed prices** by roughly two to four months.
- **Crime is a count, not a rate,** and includes footfall-driven offences such as shoplifting.
""")
    st.caption(ATTRIBUTION)


# ------------------------------------------------------------------ navigation
pages = {
    "": [st.Page(page_overview, title="Overview", default=True)],
    "Explore": [st.Page(page_homes, title="Homes", url_path="homes"),
                st.Page(page_places, title="Places", url_path="places"),
                st.Page(page_timing, title="Timing and tax", url_path="timing"),
                st.Page(page_address, title="Clues in the address", url_path="address"),
                st.Page(page_crime, title="Crime", url_path="crime")],
    "Valuation": [st.Page(page_value, title="Value a home", url_path="value"),
                  st.Page(page_accuracy, title="How accurate is it?", url_path="accuracy"),
                  st.Page(page_models, title="Model checks", url_path="models")],
    "Reference": [st.Page(page_data, title="About the data", url_path="data")],
}
st.navigation(pages).run()
