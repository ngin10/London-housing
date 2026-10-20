"""London Property Prices - price estimator, market analytics and model transparency.

    streamlit run app.py

If the processed data or trained model are missing (e.g. a fresh deploy), the app
builds them on first start by running src.build_dataset and src.train.
"""
import json
import re
import subprocess
import sys

import altair as alt
import lightgbm as lgb
import numpy as np
import pandas as pd
import streamlit as st

from src.clean import normalise_postcode
from src.config import OUTPUT_DIR, PROCESSED_DIR, ROOT
from src.features import CATEGORICAL

DATA_PATH = PROCESSED_DIR / "london_sales.parquet"
MODEL_PATH = OUTPUT_DIR / "lgbm_model.txt"
METRICS_PATH = OUTPUT_DIR / "metrics.json"
PRED_PATH = OUTPUT_DIR / "test_predictions.csv"
IMPORTANCE_PATH = OUTPUT_DIR / "feature_importance.csv"
LAG_WINDOW = 6
MIN_BOROUGH_SALES = 30

GREEN, GREEN_MID, GREEN_LIGHT, SAND = "#2F7D5B", "#5FA47F", "#A8D5BA", "#D9A55B"
INK, MUTED = "#1F3A2E", "#5B7A6B"
TYPE_ORDER = ["Flat/Maisonette", "Terraced", "Semi-detached", "Detached"]
TYPE_COLORS = [GREEN, GREEN_MID, GREEN_LIGHT, SAND]
TYPE_SCALE = alt.Scale(domain=TYPE_ORDER, range=TYPE_COLORS)
LOG_TICKS = [1e5, 2.5e5, 5e5, 1e6, 2.5e6, 5e6]
GBP_AXIS = ("datum.value >= 1e6 ? '£' + format(datum.value / 1e6, '.1f') + 'm' : "
            "'£' + format(datum.value / 1e3, ',.0f') + 'k'")

st.set_page_config(page_title="London Property Prices", page_icon="🌿", layout="wide",
                   menu_items={"About": "London house price estimator built on HM Land Registry data."})


# ===================================================================== styling

st.markdown("""
<style>
.block-container {padding-top: 2rem; max-width: 1280px;}
.hero {background: linear-gradient(135deg, #2F7D5B 0%, #5FA47F 100%); color: #FFFFFF;
       padding: 1.6rem 2rem; border-radius: 16px; margin-bottom: 1.2rem;}
.hero h1 {color: #FFFFFF; margin: 0; font-size: 2.1rem;}
.hero p {color: #E8F4EC; margin: 0.4rem 0 0; font-size: 0.95rem;}
[data-testid="stMetric"] {background: #FFFFFF; border: 1px solid #D3E6DA; border-radius: 14px;
       padding: 1rem 1.2rem; box-shadow: 0 2px 6px rgba(47,125,91,0.08);}
[data-testid="stMetricValue"] {color: #2F7D5B;}
.estimate-card {background: #FFFFFF; border-left: 6px solid #2F7D5B; border-radius: 14px;
       padding: 1.3rem 1.5rem; box-shadow: 0 2px 8px rgba(47,125,91,0.10); margin-bottom: 1rem;}
.estimate-card .label {color: #5B7A6B; font-size: 0.9rem; margin: 0;}
.estimate-card .value {color: #2F7D5B; font-size: 2.6rem; font-weight: 700; margin: 0.1rem 0;}
.estimate-card .range {color: #1F3A2E; font-size: 0.95rem; margin: 0;}
.pill {display: inline-block; padding: 0.15rem 0.7rem; border-radius: 999px; font-size: 0.82rem;
       font-weight: 600; margin-top: 0.6rem;}
.pill.high {background: #D6EEDF; color: #1E6045;}
.pill.medium {background: #F6EBD3; color: #8A6116;}
.pill.low {background: #F5DCD7; color: #8E3B2E;}
.note {background: #E3EFE7; border-radius: 10px; padding: 0.7rem 1rem; color: #1F3A2E;
       font-size: 0.92rem; margin-bottom: 0.6rem;}
.section-intro {color: #5B7A6B; font-size: 0.95rem; margin-top: -0.4rem;}
.stButton > button[kind="primary"] {background: #2F7D5B; border-color: #2F7D5B;
       border-radius: 10px; font-weight: 600;}
.stButton > button[kind="primary"]:hover {background: #24664A; border-color: #24664A;}
.stTabs [data-baseweb="tab-list"] {gap: 1.2rem;}
</style>
""", unsafe_allow_html=True)


# ===================================================================== helpers
def gbp(x: float) -> str:
    if pd.isna(x):
        return "–"
    return f"£{x/1e6:,.2f}m" if x >= 1e6 else f"£{x/1e3:,.0f}k"


def nice_borough(name: str) -> str:
    for word in [" And ", " Of ", " Upon "]:
        name = name.replace(word, word.lower())
    return name


def note(text: str) -> None:
    st.markdown(f'<div class="note">{text}</div>', unsafe_allow_html=True)


def intro(text: str) -> None:
    st.markdown(f'<p class="section-intro">{text}</p>', unsafe_allow_html=True)


def show(chart: alt.Chart) -> None:
    st.altair_chart(chart, width="stretch")


# ===================================================================== artifacts
def ensure_artifacts() -> None:
    """Build data and train the model if missing, e.g. on a fresh cloud deploy."""
    if DATA_PATH.exists() and MODEL_PATH.exists() and PRED_PATH.exists():
        return
    with st.status("First start: building the dataset and training the model…",
                   expanded=True) as status:
        for step, module in [("Cleaning and joining sales data", "src.build_dataset"),
                             ("Training the price model", "src.train")]:
            st.write(step + "…")
            result = subprocess.run([sys.executable, "-m", module], cwd=ROOT,
                                    capture_output=True, text=True)
            if result.returncode != 0:
                status.update(label="Setup failed", state="error")
                st.code(result.stderr[-3000:])
                st.stop()
        status.update(label="Ready", state="complete", expanded=False)


@st.cache_data(show_spinner=False)
def load_data() -> pd.DataFrame:
    df = pd.read_parquet(DATA_PATH)
    df["date"] = pd.to_datetime(df["date"])
    df["month_start"] = df["date"].dt.to_period("M").dt.to_timestamp()
    df["borough_name"] = df["borough"].map(nice_borough)
    return df


@st.cache_resource(show_spinner=False)
def load_model() -> lgb.Booster:
    return lgb.Booster(model_file=str(MODEL_PATH))


@st.cache_data(show_spinner=False)
def load_evaluation():
    metrics = json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else None
    preds = pd.read_csv(PRED_PATH, parse_dates=["date"]) if PRED_PATH.exists() else None
    if preds is not None:
        preds["pct_error"] = preds["pred_price"] / preds["price"] - 1
        preds["ape"] = preds["pct_error"].abs()
        preds["borough_name"] = preds["borough"].map(nice_borough)
    imp = pd.read_csv(IMPORTANCE_PATH) if IMPORTANCE_PATH.exists() else None
    if imp is not None:
        imp.columns = ["feature", "importance"]
    return metrics, preds, imp


@st.cache_data(show_spinner=False)
def area_lookups(df: pd.DataFrame) -> dict:
    """Latest area-level inputs, built the same way as in training."""
    months = pd.PeriodIndex(df["month"], freq="M")
    recent = df[months > months.max() - LAG_WINDOW].assign(m=months[months > months.max() - LAG_WINDOW])
    lag = {lvl: recent.groupby([lvl, "m"])["log_price"].median().groupby(lvl).mean()
           for lvl in ["postcode_sector", "outward_code"]}
    loc_cols = ["latitude", "longitude", "crimes_12m", "burglaries_12m"]
    by_pc = df.groupby("postcode").agg(**{c: (c, "mean") for c in loc_cols},
                                       postcode_sector=("postcode_sector", "first"),
                                       outward_code=("outward_code", "first"),
                                       borough=("borough", "first"))
    by_sector = df.groupby("postcode_sector").agg(**{c: (c, "mean") for c in loc_cols},
                                                  outward_code=("outward_code", "first"),
                                                  borough=("borough", lambda s: s.mode().iat[0]))
    return {"lag": lag, "postcode": by_pc, "sector": by_sector, "latest_month": months.max(),
            "months_since_start": int(df["months_since_start"].max())}


# ===================================================================== estimator logic
def resolve_location(postcode: str, lk: dict):
    pc = normalise_postcode(pd.Series([postcode])).iat[0]
    if pd.isna(pc) or not re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}", pc):
        return None, None, f"“{postcode}” doesn’t look like a UK postcode (e.g. SW11 1AA)."
    if pc in lk["postcode"].index:
        return pc, lk["postcode"].loc[pc].to_dict() | {"exact": True}, None
    sector = pc[:-2]
    if sector in lk["sector"].index:
        row = lk["sector"].loc[sector].to_dict() | {"postcode_sector": sector, "exact": False}
        return pc, row, f"No sales recorded at {pc}, so the estimate uses postcode sector {sector}."
    return pc, None, (f"There are no sales in the data for {pc} or its sector. Coverage is London "
                      "postal districts (E, EC, N, NW, SE, SW, W and WC).")


def predict(model, loc, property_type, tenure, new_build, lk) -> float:
    row = {
        "property_type": property_type, "tenure": tenure, "borough": loc["borough"],
        "outward_code": loc["outward_code"], "new_build": int(new_build),
        "months_since_start": lk["months_since_start"],
        "sale_month_of_year": lk["latest_month"].month,
        "latitude": loc["latitude"], "longitude": loc["longitude"],
        f"postcode_sector_lag{LAG_WINDOW}m_log_price":
            lk["lag"]["postcode_sector"].get(loc["postcode_sector"], np.nan),
        f"outward_code_lag{LAG_WINDOW}m_log_price":
            lk["lag"]["outward_code"].get(loc["outward_code"], np.nan),
        "crimes_12m": loc["crimes_12m"], "burglaries_12m": loc["burglaries_12m"],
    }
    X = pd.DataFrame([row]).reindex(columns=model.feature_name())
    for c in CATEGORICAL:
        if c in X:
            X[c] = X[c].astype("category")
    return float(np.exp(model.predict(X))[0])


def confidence(comps: pd.DataFrame, area_error: float, exact: bool) -> tuple[str, str]:
    """Simple, explainable confidence rating from local evidence and measured error."""
    n = len(comps)
    spread = comps["log_price"].std() if n >= 5 else np.inf
    score = (n >= 20) + (n >= 8) + (spread < 0.35) + (area_error < 0.18) + exact
    if score >= 4:
        return "high", "High confidence"
    if score >= 2:
        return "medium", "Medium confidence"
    return "low", "Low confidence"


# ===================================================================== app start
ensure_artifacts()
df = load_data()
model = load_model()
lk = area_lookups(df)
metrics, preds, importance = load_evaluation()
overall_mdape = metrics["model"]["median_APE"] if metrics else 0.2
borough_mdape = (preds.groupby("borough")["ape"].agg(["median", "size"])
                 if preds is not None else pd.DataFrame(columns=["median", "size"]))

st.markdown(f"""
<div class="hero">
  <h1>🌿 London Property Prices</h1>
  <p>Estimate what a London home sells for and explore {len(df):,} residential sales from
  {df['date'].min():%B %Y} to {df['date'].max():%B %Y}.</p>
</div>""", unsafe_allow_html=True)

tab_est, tab_market, tab_compare, tab_model, tab_about = st.tabs(
    ["Estimate a price", "Market overview", "Compare areas", "Model performance", "About"])

# ===================================================================== 1. estimator
with tab_est:
    qp = st.query_params
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        postcode = st.text_input("Postcode", value=qp.get("postcode", "SW11 1AA"),
                                 help="Any London postcode, e.g. E1 6AN or SW11 1AA")
        default_type = qp.get("type", "Flat/Maisonette")
        property_type = st.selectbox("Property type", TYPE_ORDER,
                                     index=TYPE_ORDER.index(default_type) if default_type in TYPE_ORDER else 0)
        tenure = st.radio("Tenure", ["Freehold", "Leasehold"], horizontal=True,
                          index=1 if property_type == "Flat/Maisonette" else 0)
        new_build = st.checkbox("New build")
        go = st.button("Estimate price", type="primary", width="stretch")
        st.caption("The model has no floor area or bedroom data, so an estimate describes a "
                   "typical home of this type in this location, not one specific property.")

    with right:
        if not go and "postcode" not in qp:
            note("Enter a postcode and property details, then press <b>Estimate price</b>.")
        else:
            pc, loc, msg = resolve_location(postcode, lk)
            if loc is None:
                st.warning(msg)
            else:
                st.query_params.update({"postcode": pc, "type": property_type})
                estimate = predict(model, loc, property_type, tenure, new_build, lk)
                b_err = borough_mdape["median"].get(loc["borough"], np.nan)
                b_n = borough_mdape["size"].get(loc["borough"], 0)
                err = b_err if b_n >= 50 else overall_mdape
                err_src = (f"the model’s {err:.0%} median error in {nice_borough(loc['borough'])}"
                           if b_n >= 50 else f"the model’s {err:.0%} median error across London")

                comps = df[(df["postcode_sector"] == loc["postcode_sector"])
                           & (df["property_type"] == property_type)]
                comp_area = f"sector {loc['postcode_sector']}"
                if len(comps) < 8:
                    comps = df[(df["outward_code"] == loc["outward_code"])
                               & (df["property_type"] == property_type)]
                    comp_area = f"district {loc['outward_code']}"
                level, label = confidence(comps, err, loc["exact"])

                st.markdown(f"""
<div class="estimate-card">
  <p class="label">Estimated price · {property_type.lower()}, {tenure.lower()}{', new build' if new_build else ''}</p>
  <p class="value">{gbp(estimate)}</p>
  <p class="range">Likely range {gbp(estimate * (1 - err))} – {gbp(estimate * (1 + err))},
  based on {err_src} on unseen recent sales.</p>
  <span class="pill {level}">{label}</span>
</div>""", unsafe_allow_html=True)
                if msg:
                    note("ℹ️ " + msg)
                st.caption(f"{pc} · {nice_borough(loc['borough'])} · sector {loc['postcode_sector']} · "
                           "this page’s link now includes your search, so you can share it")

    if (go or "postcode" in qp) and loc is not None:
        st.divider()
        st.subheader(f"How this compares with {property_type.lower()} sales in {comp_area}")
        intro(f"{len(comps):,} sales, median {gbp(comps['price'].median())}. The line marks this estimate.")
        c1, c2 = st.columns([1.4, 1], gap="large")
        with c1:
            hist_data = comps[comps["price"] <= comps["price"].quantile(0.98)]
            hist = alt.Chart(hist_data).mark_bar(color=GREEN_LIGHT, cornerRadiusTopLeft=3,
                                                 cornerRadiusTopRight=3).encode(
                x=alt.X("price:Q", bin=alt.Bin(maxbins=25), title="Sale price",
                        axis=alt.Axis(labelExpr=GBP_AXIS)),
                y=alt.Y("count():Q", title="Sales"))
            rule = alt.Chart(pd.DataFrame({"price": [estimate]})).mark_rule(
                color=GREEN, strokeWidth=3).encode(x="price:Q")
            show((hist + rule).properties(height=280))
        with c2:
            sector_types = (df[df["postcode_sector"] == loc["postcode_sector"]]
                            .groupby("property_type")["price"].agg(median="median", sales="size")
                            .reindex(TYPE_ORDER).dropna().reset_index())
            sector_types["label"] = sector_types["median"].map(gbp)
            base = alt.Chart(sector_types).encode(
                y=alt.Y("property_type:N", sort=TYPE_ORDER, title=None),
                x=alt.X("median:Q", title=f"Median price in {loc['postcode_sector']}",
                        axis=alt.Axis(labelExpr=GBP_AXIS)))
            show((base.mark_bar(cornerRadiusEnd=4).encode(
                      color=alt.Color("property_type:N", scale=TYPE_SCALE, legend=None),
                      tooltip=["property_type", "label", "sales"])
                  + base.mark_text(align="left", dx=4, color=INK).encode(text="label:N"))
                 .properties(height=280))

        st.subheader("Most recent comparable sales")
        st.dataframe(
            comps.sort_values("date", ascending=False).head(12)[["date", "postcode", "tenure", "new_build", "price"]]
                 .assign(new_build=lambda d: np.where(d["new_build"] == 1, "Yes", "No"),
                         price=lambda d: d["price"].map("£{:,.0f}".format)),
            hide_index=True, width="stretch",
            column_config={"date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                           "postcode": "Postcode", "tenure": "Tenure", "new_build": "New build",
                           "price": "Price"})

# ===================================================================== 2. market overview
with tab_market:
    f1, f2, f3 = st.columns([2, 2, 1])
    boroughs = sorted(df["borough"].unique())
    sel_b = f1.multiselect("Boroughs", boroughs, format_func=nice_borough, placeholder="All boroughs")
    sel_t = f2.multiselect("Property types", TYPE_ORDER, placeholder="All types")
    nb_filter = f3.selectbox("Build", ["All", "New build", "Existing"])
    view = df
    if sel_b:
        view = view[view["borough"].isin(sel_b)]
    if sel_t:
        view = view[view["property_type"].isin(sel_t)]
    if nb_filter != "All":
        view = view[view["new_build"] == (1 if nb_filter == "New build" else 0)]

    if view.empty:
        st.warning("No sales match these filters.")
    else:
        last = view["month_start"].max()
        cur = view[view["month_start"] > last - pd.DateOffset(months=3)]
        prev = view[(view["month_start"] <= last - pd.DateOffset(months=3))
                    & (view["month_start"] > last - pd.DateOffset(months=6))]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Sales", f"{len(view):,}")
        k2.metric("Median price", gbp(view["price"].median()))
        if len(prev) >= 20 and len(cur) >= 20:
            chg = cur["price"].median() / prev["price"].median() - 1
            k3.metric("Median, last 3 months", gbp(cur["price"].median()), f"{chg:+.1%} vs prior 3 months")
        else:
            k3.metric("Median, last 3 months", gbp(cur["price"].median()))
        k4.metric("New-build share", f"{view['new_build'].mean():.1%}")
        st.caption("The latest months are incomplete because sales take several weeks to reach "
                   "the Land Registry, so recent volumes understate activity.")

        st.subheader("Prices and activity over time")
        c1, c2 = st.columns(2, gap="large")
        with c1:
            mt = (view.groupby(["month_start", "property_type"])["price"]
                      .agg(median="median", sales="size").reset_index())
            mt = mt[mt["sales"] >= 15]
            show(alt.Chart(mt).mark_line(point=alt.OverlayMarkDef(size=30), strokeWidth=2.5).encode(
                x=alt.X("month_start:T", title=None, axis=alt.Axis(format="%b %y")),
                y=alt.Y("median:Q", title="Median price", axis=alt.Axis(labelExpr=GBP_AXIS),
                        scale=alt.Scale(type="log")),
                color=alt.Color("property_type:N", scale=TYPE_SCALE, title=None, legend=alt.Legend(orient="top")),
                tooltip=[alt.Tooltip("month_start:T", format="%B %Y", title="Month"),
                         alt.Tooltip("property_type:N", title="Type"),
                         alt.Tooltip("median:Q", format=",.0f", title="Median £"),
                         alt.Tooltip("sales:Q", title="Sales")]).properties(
                title="Median price by property type (log scale)", height=300))
        with c2:
            vol = view.groupby(["month_start", "property_type"]).size().rename("sales").reset_index()
            show(alt.Chart(vol).mark_bar().encode(
                x=alt.X("yearmonth(month_start):O", title=None,
                        axis=alt.Axis(format="%b %y", labelAngle=0)),
                y=alt.Y("sales:Q", title="Completed sales"),
                color=alt.Color("property_type:N", scale=TYPE_SCALE, title=None, sort=TYPE_ORDER, legend=alt.Legend(orient="top")),
                order=alt.Order("property_type:N"),
                tooltip=[alt.Tooltip("yearmonth(month_start):O", title="Month"),
                         "property_type", "sales"]).properties(
                title="Monthly completions by type", height=300))
        note("📌 March 2025 volumes spike ahead of the 1 April 2025 stamp duty change, when the "
             "nil-rate threshold fell from £250k to £125k. Cheaper homes were pulled forward, which "
             "also distorts raw monthly medians.")

        st.subheader("Price distribution")
        c1, c2 = st.columns([1.4, 1], gap="large")
        with c1:
            dist = view[view["price"] <= view["price"].quantile(0.99)]
            show(alt.Chart(dist).mark_bar(opacity=0.85).encode(
                x=alt.X("price:Q", bin=alt.Bin(maxbins=60), title="Sale price (to 99th percentile)",
                        axis=alt.Axis(labelExpr=GBP_AXIS)),
                y=alt.Y("count():Q", title="Sales", stack=True),
                color=alt.Color("property_type:N", scale=TYPE_SCALE, title=None,
                                legend=alt.Legend(orient="top"))).properties(height=300))
        with c2:
            bands = pd.cut(view["price"], [0, 300e3, 500e3, 750e3, 1e6, 2e6, np.inf],
                           labels=["<£300k", "£300–500k", "£500–750k", "£750k–1m", "£1–2m", "£2m+"])
            bd = bands.value_counts(normalize=True).sort_index().rename("share").reset_index()
            bd.columns = ["band", "share"]
            show(alt.Chart(bd).mark_bar(color=GREEN, cornerRadiusEnd=4).encode(
                y=alt.Y("band:N", sort=None, title=None),
                x=alt.X("share:Q", title="Share of sales", axis=alt.Axis(format="%")),
                tooltip=[alt.Tooltip("share:Q", format=".1%")]).properties(
                title="Sales by price band", height=300))

        st.subheader("Boroughs")
        bm = (view.groupby("borough_name")
                  .agg(median_price=("price", "median"), sales=("price", "size"),
                       new_build=("new_build", "mean")).reset_index())
        hidden = bm[bm["sales"] < MIN_BOROUGH_SALES]
        bm = bm[bm["sales"] >= MIN_BOROUGH_SALES]
        bm["label"] = bm["median_price"].map(gbp)
        c1, c2 = st.columns([1, 1], gap="large")
        with c1:
            base = alt.Chart(bm).encode(
                y=alt.Y("borough_name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=200)),
                x=alt.X("median_price:Q", title="Median price", axis=alt.Axis(labelExpr=GBP_AXIS)))
            show((base.mark_bar(color=GREEN, cornerRadiusEnd=4).encode(
                      tooltip=[alt.Tooltip("borough_name:N", title="Borough"),
                               alt.Tooltip("label:N", title="Median"),
                               alt.Tooltip("sales:Q", format=",", title="Sales")])
                  + base.mark_text(align="left", dx=4, color=INK, fontSize=11).encode(text="label:N"))
                 .properties(title="Median price", height=alt.Step(24)))
        with c2:
            mix = (view[view["borough_name"].isin(bm["borough_name"])]
                   .groupby(["borough_name", "property_type"]).size().rename("n").reset_index())
            order = bm.sort_values("median_price", ascending=False)["borough_name"].tolist()
            show(alt.Chart(mix).mark_bar().encode(
                y=alt.Y("borough_name:N", sort=order, title=None, axis=alt.Axis(labelLimit=200)),
                x=alt.X("n:Q", stack="normalize", title="Share of sales", axis=alt.Axis(format="%")),
                color=alt.Color("property_type:N", scale=TYPE_SCALE, title=None, sort=TYPE_ORDER,
                                legend=alt.Legend(orient="bottom", columns=2, labelLimit=140)),
                order=alt.Order("property_type:N"),
                tooltip=["borough_name", "property_type", "n"]).properties(
                title="Property-type mix (same order)", height=alt.Step(24)))
        if len(hidden):
            st.caption(f"Not shown (fewer than {MIN_BOROUGH_SALES} sales): "
                       + ", ".join(f"{b} ({n})" for b, n in zip(hidden["borough_name"], hidden["sales"])))
        intro("Borough medians partly reflect the mix of homes sold: boroughs selling more "
              "houses look more expensive even at similar values per home.")

        st.subheader("Where prices are highest")
        geo = view.dropna(subset=["latitude", "longitude"]).copy()
        band_edges = [0, 400e3, 500e3, 650e3, 850e3, 1.2e6, np.inf]
        band_names = ["Under £400k", "£400–500k", "£500–650k", "£650–850k", "£850k–1.2m", "Over £1.2m"]
        band_rgb = [[214, 236, 222], [168, 213, 186], [127, 184, 154], [79, 150, 115],
                    [47, 125, 91], [217, 165, 91]]
        geo["band"] = pd.cut(geo["price"], band_edges, labels=False)
        geo["color"] = geo["band"].map(
            lambda i: "#{:02x}{:02x}{:02x}cc".format(*band_rgb[int(i)]))
        legend = " ".join(
            f'<span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
            f'background:rgb({r},{g},{b});margin:0 4px 0 12px;vertical-align:middle"></span>{n}'
            for (r, g, b), n in zip(band_rgb, band_names))
        st.markdown(f'<p class="section-intro">Each dot is a sale, coloured by price. Scroll to '
                    f'zoom into streets.<br>{legend}</p>', unsafe_allow_html=True)
        st.map(geo[["latitude", "longitude", "color"]], latitude="latitude", longitude="longitude",
               color="color", size=15, height=540)

        st.download_button("⬇️ Download filtered sales (CSV)",
                           view[["date", "postcode", "borough_name", "property_type", "tenure",
                                 "new_build", "price"]].to_csv(index=False).encode(),
                           file_name="london_sales_filtered.csv", mime="text/csv")

# ===================================================================== 3. compare areas
with tab_compare:
    intro("Pick up to four boroughs to compare like with like.")
    eligible = df.groupby("borough").size()
    eligible = sorted(eligible[eligible >= MIN_BOROUGH_SALES].index)
    picks = st.multiselect("Boroughs to compare", eligible, max_selections=4,
                           default=[b for b in ["Hackney", "Wandsworth", "Croydon"] if b in eligible],
                           format_func=nice_borough)
    if len(picks) < 2:
        note("Choose at least two boroughs.")
    else:
        sub = df[df["borough"].isin(picks)]
        cols = st.columns(len(picks))
        for col, b in zip(cols, picks):
            s = sub[sub["borough"] == b]
            col.metric(f"{nice_borough(b)} · {len(s):,} sales", gbp(s["price"].median()))

        c1, c2 = st.columns(2, gap="large")
        with c1:
            bt = (sub.groupby(["borough_name", "property_type"])["price"]
                     .agg(median="median", sales="size").reset_index())
            bt = bt[bt["sales"] >= 10]
            show(alt.Chart(bt).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                x=alt.X("property_type:N", sort=TYPE_ORDER, title=None, axis=alt.Axis(labelAngle=0)),
                xOffset=alt.XOffset("borough_name:N"),
                y=alt.Y("median:Q", title="Median price", axis=alt.Axis(labelExpr=GBP_AXIS)),
                color=alt.Color("borough_name:N", title=None, legend=alt.Legend(orient="top"),
                                scale=alt.Scale(range=[GREEN, SAND, GREEN_LIGHT, "#7E9C8C"])),
                tooltip=["borough_name", "property_type", alt.Tooltip("median:Q", format=",.0f"), "sales"])
                .properties(title="Median price by property type", height=320))
        with c2:
            tr = (sub.groupby(["borough_name", "month_start"])["price"].median()
                     .rename("median").reset_index().sort_values("month_start"))
            tr["rolling"] = tr.groupby("borough_name")["median"].transform(
                lambda s: s.rolling(3, min_periods=1).mean())
            show(alt.Chart(tr).mark_line(strokeWidth=2.5).encode(
                x=alt.X("month_start:T", title=None, axis=alt.Axis(format="%b %y")),
                y=alt.Y("rolling:Q", title="Median price (3-month rolling)",
                        axis=alt.Axis(labelExpr=GBP_AXIS), scale=alt.Scale(zero=False)),
                color=alt.Color("borough_name:N", title=None, legend=alt.Legend(orient="top"),
                                scale=alt.Scale(range=[GREEN, SAND, GREEN_LIGHT, "#7E9C8C"])),
                tooltip=["borough_name", alt.Tooltip("month_start:T", format="%B %Y"),
                         alt.Tooltip("rolling:Q", format=",.0f")])
                .properties(title="Price trend", height=320))

        show(alt.Chart(sub[sub["price"] <= sub["price"].quantile(0.99)]).mark_boxplot(
                extent=1.5, size=38, outliers=False, median={"color": "white"}).encode(
            y=alt.Y("borough_name:N", title=None),
            x=alt.X("price:Q", title="Sale price (box = middle 50% of sales, log scale)",
                    axis=alt.Axis(labelExpr=GBP_AXIS, values=LOG_TICKS),
                    scale=alt.Scale(type="log", domain=[8e4, 8e6])),
            color=alt.Color("borough_name:N", legend=None,
                            scale=alt.Scale(range=[GREEN, SAND, GREEN_LIGHT, "#7E9C8C"])))
             .properties(title="Spread of prices", height=70 * len(picks) + 40))

        summary = (sub.groupby("borough_name").agg(
            sales=("price", "size"), median=("price", "median"),
            flats=("property_type", lambda s: (s == "Flat/Maisonette").mean()),
            new_build=("new_build", "mean"), crimes=("crimes_12m", "median")).reset_index())
        summary = summary.assign(sales=summary["sales"].map("{:,}".format),
                                 median=summary["median"].map("£{:,.0f}".format),
                                 flats=summary["flats"].map("{:.0%}".format),
                                 new_build=summary["new_build"].map("{:.1%}".format),
                                 crimes=summary["crimes"].map("{:,.0f}".format))
        summary.columns = ["Borough", "Sales", "Median price", "Flats", "New build",
                           "Median crimes per LSOA (12m)"]
        st.dataframe(summary, hide_index=True, width="stretch")

# ===================================================================== 4. model performance
with tab_model:
    if metrics is None or preds is None:
        st.warning("Model evaluation files not found. Run `python -m src.train`.")
    else:
        m, b = metrics["model"], metrics["baseline_sector_median"]
        intro(f"Trained on {metrics['n_train']:,} sales and tested on {metrics['n_test']:,} later sales "
              f"from {metrics['test_from']} onwards, which the model never saw.")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Median error", f"{m['median_APE']:.1%}",
                  f"{(m['median_APE'] - b['median_APE']) * 100:+.1f} pts vs baseline", delta_color="inverse")
        k2.metric("Within ±10%", f"{m['within_10pct']:.0%}",
                  f"{(m['within_10pct'] - b['within_10pct']) * 100:+.0f} pts vs baseline")
        k3.metric("Within ±20%", f"{m['within_20pct']:.0%}",
                  f"{(m['within_20pct'] - b['within_20pct']) * 100:+.0f} pts vs baseline")
        k4.metric("Mean absolute error", gbp(m["MAE_gbp"]))
        st.caption("Baseline: the previous six months’ median price in the same postcode sector.")

        c1, c2 = st.columns(2, gap="large")
        with c1:
            sample = preds.sample(min(len(preds), 4000), random_state=0)
            lo, hi = 8e4, 8e6
            pts = alt.Chart(sample).mark_circle(size=14, opacity=0.35, color=GREEN).encode(
                x=alt.X("price:Q", title="Actual sale price", scale=alt.Scale(type="log", domain=[lo, hi], clamp=True),
                        axis=alt.Axis(labelExpr=GBP_AXIS, values=LOG_TICKS)),
                y=alt.Y("pred_price:Q", title="Predicted price", scale=alt.Scale(type="log", domain=[lo, hi], clamp=True),
                        axis=alt.Axis(labelExpr=GBP_AXIS, values=LOG_TICKS)),
                tooltip=["postcode", "property_type", alt.Tooltip("price:Q", format=",.0f"),
                         alt.Tooltip("pred_price:Q", format=",.0f")])
            line = alt.Chart(pd.DataFrame({"v": [lo, hi]})).mark_line(
                color=SAND, strokeDash=[6, 4], strokeWidth=2).encode(x="v:Q", y="v:Q")
            show((pts + line).properties(title="Predicted vs actual (dashed = perfect)", height=360))
        with c2:
            err = preds[preds["pct_error"].between(-1, 1.5)]
            show(alt.Chart(err).mark_bar(color=GREEN_MID).encode(
                x=alt.X("pct_error:Q", bin=alt.Bin(step=0.05), title="Prediction error (predicted ÷ actual − 1)",
                        axis=alt.Axis(format="%")),
                y=alt.Y("count():Q", title="Sales")).properties(
                title="Distribution of errors", height=360))

        c1, c2 = st.columns(2, gap="large")
        with c1:
            et = preds.groupby("property_type")["ape"].agg(median="median", sales="size").reindex(TYPE_ORDER).reset_index()
            show(alt.Chart(et).mark_bar(cornerRadiusEnd=4).encode(
                y=alt.Y("property_type:N", sort=TYPE_ORDER, title=None),
                x=alt.X("median:Q", title="Median absolute error", axis=alt.Axis(format="%")),
                color=alt.Color("property_type:N", scale=TYPE_SCALE, legend=None),
                tooltip=[alt.Tooltip("median:Q", format=".1%"), "sales"])
                .properties(title="Error by property type", height=240))
        with c2:
            bands = pd.cut(preds["pred_price"], [0, 300e3, 500e3, 750e3, 1e6, 2e6, np.inf],
                           labels=["<£300k", "£300–500k", "£500–750k", "£750k–1m", "£1–2m", "£2m+"])
            eb = preds.groupby(bands, observed=True)["ape"].agg(median="median", sales="size").reset_index()
            eb.columns = ["band", "median", "sales"]
            show(alt.Chart(eb).mark_bar(color=GREEN, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                x=alt.X("band:N", sort=None, title="Predicted value band", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("median:Q", title="Median absolute error", axis=alt.Axis(format="%")),
                tooltip=[alt.Tooltip("median:Q", format=".1%"), "sales"])
                .properties(title="Error by predicted value", height=240))

        c1, c2 = st.columns(2, gap="large")
        with c1:
            eb2 = preds.groupby("borough_name")["ape"].agg(median="median", sales="size").reset_index()
            eb2 = eb2[eb2["sales"] >= 50]
            show(alt.Chart(eb2).mark_bar(cornerRadiusEnd=4).encode(
                y=alt.Y("borough_name:N", sort="x", title=None, axis=alt.Axis(labelLimit=200)),
                x=alt.X("median:Q", title="Median absolute error", axis=alt.Axis(format="%")),
                color=alt.Color("median:Q", legend=None,
                                scale=alt.Scale(range=[GREEN_LIGHT, GREEN, "#18523A"])),
                tooltip=["borough_name", alt.Tooltip("median:Q", format=".1%"), "sales"])
                .properties(title="Error by borough (≥50 test sales)", height=alt.Step(22)))

        with c2:
            if importance is not None:
                labels = {"latitude": "Latitude", "longitude": "Longitude", "crimes_12m": "Crimes (12m, LSOA)",
                          "burglaries_12m": "Burglaries (12m, LSOA)",
                          f"postcode_sector_lag{LAG_WINDOW}m_log_price": "Recent sector prices",
                          f"outward_code_lag{LAG_WINDOW}m_log_price": "Recent district prices",
                          "outward_code": "Postcode district", "months_since_start": "Time trend",
                          "borough": "Borough", "property_type": "Property type", "tenure": "Tenure",
                          "sale_month_of_year": "Month of year", "new_build": "New build"}
                imp = importance.assign(feature=importance["feature"].map(lambda f: labels.get(f, f)))
                imp["share"] = imp["importance"] / imp["importance"].sum()
                show(alt.Chart(imp).mark_bar(color=GREEN, cornerRadiusEnd=4).encode(
                    y=alt.Y("feature:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220)),
                    x=alt.X("share:Q", title="Share of tree splits", axis=alt.Axis(format="%")),
                    tooltip=[alt.Tooltip("share:Q", format=".1%")])
                    .properties(title="What the model relies on", height=alt.Step(22)))
                st.caption("Split counts show how often the model uses a feature, not how much each "
                           "changes the price. Location dominates because size data is unavailable.")

# ===================================================================== 5. about
with tab_about:
    c1, c2 = st.columns([1.3, 1], gap="large")
    with c1:
        st.markdown(f"""
### How it works
**Data.** {len(df):,} standard residential sales (Land Registry category A) in London postal
districts, {df['date'].min():%B %Y} – {df['date'].max():%B %Y}, joined at postcode level with
coordinates, LSOA and 12-month crime counts.

**Model.** A LightGBM gradient-boosted tree model trained on log price. Features include
property type, tenure, new-build status, location (coordinates, borough, postcode district),
recent local prices (six-month medians at sector and district level, using only earlier months),
crime counts and a time trend.

**Validation.** A time-based split: the model is trained on earlier months and tested on the
most recent ones, so reported accuracy reflects how it performs on sales it has never seen.

**Confidence rating.** Each estimate is rated from the number of comparable sales nearby, how
widely their prices vary, the model's measured error in that borough, and whether the exact
postcode appears in the data.
""")
    with c2:
        st.markdown("""
### Limitations
- **No floor area or bedrooms.** Size is the biggest driver of price, so estimates describe a
  typical home of that type in that area.
- **Coverage** is London postal districts only; some outer boroughs are thin or missing.
- **One year of data** including the April 2025 stamp duty change.
- **Completion prices lag agreed prices** by roughly two to four months.
- Not a formal valuation, and not financial advice.

### Sources
Contains HM Land Registry data © Crown copyright and database right 2026, licensed under the
Open Government Licence v3.0. Postcode geography from postcodes.io (ONS). Crime data from
data.police.uk under the Open Government Licence v3.0.
""")

st.divider()
st.caption("Contains HM Land Registry data © Crown copyright and database right 2026, licensed under "
           "the Open Government Licence v3.0. Estimates are indicative only.")
