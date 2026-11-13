"""Data preparation and analysis for the London property explorer.

Everything here is pure pandas / statsmodels so it can be tested without Streamlit.
The app wraps these functions in st.cache_data so each runs once per session.
"""
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.neighbors import NearestNeighbors

CENTRE = (51.5074, -0.1278)  # Charing Cross
TYPE_NAMES = {"F": "Flat", "T": "Terraced", "S": "Semi-detached", "D": "Detached"}
TYPE_ORDER = ["Flat", "Terraced", "Semi-detached", "Detached"]
LONDON_PART = {"EC": "Central", "WC": "Central", "E": "East", "N": "North", "NW": "North-west",
               "SE": "South-east", "SW": "South-west", "W": "West"}
BUILDING_WORDS = {"HOUSE": "House (block)", "COURT": "Court", "APARTMENTS": "Apartments", "MANSIONS": "Mansions",
                  "BUILDING": "Building", "BUILDINGS": "Building", "TOWER": "Tower or point", "POINT": "Tower or point",
                  "HEIGHTS": "Tower or point", "WHARF": "Wharf", "LODGE": "Lodge", "HALL": "Hall"}


# ---------------------------------------------------------------- cleaning
def clean(raw: pd.DataFrame):
    """Apply the documented cleaning rules. Returns (clean dataframe, funnel table)."""
    df = raw.copy()
    funnel = [("Raw download", len(df))]

    def keep(name, mask):
        nonlocal df
        df = df[mask].copy()
        funnel.append((name, len(df)))

    keep("Standard market sales (category A)", df["transaction_category"] == "A")
    keep("Price of at least £50k", df["price_paid"] >= 50_000)
    keep("Inside Greater London", df["county"] == "GREATER LONDON")
    keep("Has map coordinates", df["latitude"].notna())
    keep("Matched to crime data", df["crimes_12m"] > 0)
    counts = df["district"].value_counts()
    keep("Borough has 100+ sales", df["district"].isin(counts[counts >= 100].index))
    area = df["postcode"].str.upper().str.extract(r"^([A-Z]+)")[0]
    keep("London postal district", area.isin(LONDON_PART.keys()))

    df = df.rename(columns={"price_paid": "price", "deed_date": "date", "estate_type": "tenure",
                            "district": "borough", "crimes_12m": "crimes", "burglaries_12m": "burglaries"})
    return add_features(df), pd.DataFrame(funnel, columns=["step", "rows"])


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df["date"] = pd.to_datetime(df["date"])
    df["log_price"] = np.log(df["price"])
    df["borough"] = (df["borough"].str.title().str.replace(" And ", " and ")
                     .str.replace(" Of ", " of ").str.replace(" Upon ", " upon "))
    df["type_name"] = df["property_type"].map(TYPE_NAMES)
    df["tenure_name"] = df["tenure"].map({"F": "Freehold", "L": "Leasehold"})
    df["is_new_build"] = (df["new_build"] == "Y").astype(int)
    df["new_build_name"] = np.where(df["is_new_build"] == 1, "New build", "Existing")

    lat, lon = np.radians(df["latitude"]), np.radians(df["longitude"])
    lat0, lon0 = np.radians(CENTRE[0]), np.radians(CENTRE[1])
    a = np.sin((lat - lat0) / 2) ** 2 + np.cos(lat) * np.cos(lat0) * np.sin((lon - lon0) / 2) ** 2
    df["km_to_centre"] = 6371 * 2 * np.arcsin(np.sqrt(a))

    pc = df["postcode"].str.upper().str.strip()
    df["postcode"] = pc
    df["pc_area"] = pc.str.extract(r"^([A-Z]+)")[0]
    df["pc_district"] = pc.str.split().str[0]
    df["pc_sector"] = pc.str[:-2].str.strip()
    df["london_part"] = df["pc_area"].map(LONDON_PART)

    saon = df["saon"].fillna("").str.upper()
    paon = df["paon"].fillna("").str.upper()
    df["floor_level"] = saon.map(_floor)
    name = paon.str.extract(r"^([A-Z][A-Z' .&-]*[A-Z])")[0]
    df["building_type"] = name.str.split().str[-1].map(BUILDING_WORDS)
    df.loc[name.notna() & df["building_type"].isna(), "building_type"] = "Other named"
    df["building_type"] = df["building_type"].fillna("Numbered only")
    street_end = df["street"].fillna("").str.split().str[-1].str.title()
    common = street_end.value_counts()
    df["street_type"] = street_end.where(street_end.isin(common[common >= 300].index), "Other")

    df["month"] = df["date"].dt.to_period("M").astype(str)
    df["weekday"] = df["date"].dt.day_name()
    df["crime_quartile"] = pd.qcut(df["crimes"], 4, labels=["Q1 lowest", "Q2", "Q3", "Q4 highest"]).astype(str)
    df["type_tenure"] = df["type_name"] + " · " + df["tenure_name"].str.lower()
    df["address"] = (df["saon"].fillna("") + " " + df["paon"].fillna("") + " " + df["street"].fillna("")).str.strip().str.title()
    return df


def _floor(s: str) -> str:
    if s == "":
        return "No unit given"
    if "PENTHOUSE" in s:
        return "Penthouse"
    if "BASEMENT" in s or "LOWER GROUND" in s:
        return "Basement"
    if "GROUND" in s or "GARDEN" in s:
        return "Ground"
    if "TOP" in s or "UPPER" in s:
        return "Top"
    for word, label in [("FIRST", "First"), ("SECOND", "Second"), ("THIRD", "Third or higher"),
                        ("FOURTH", "Third or higher"), ("FIFTH", "Third or higher")]:
        if word in s:
            return label
    return "Not stated"


# ---------------------------------------------------------------- models
def fe_r2(df, cat_x, group):
    """R² of log price on dummies(cat_x) plus fixed effects for `group`."""
    X = pd.get_dummies(df[cat_x], drop_first=True).astype(float)
    y = df["log_price"].astype(float)
    if group is None:
        Xd, yd = X - X.mean(), y - y.mean()
    else:
        g = df[group]
        Xd, yd = X - X.groupby(g).transform("mean"), y - y.groupby(g).transform("mean")
    beta, *_ = np.linalg.lstsq(Xd.values, yd.values, rcond=None)
    resid = yd.values - Xd.values @ beta
    return 1 - (resid ** 2).sum() / ((y - y.mean()) ** 2).sum()


def hedonic(df, cats, base, group):
    """Hedonic regression with `group` fixed effects. Returns (premiums table, R², residuals)."""
    X = pd.concat([pd.get_dummies(df[c], prefix=c, prefix_sep="=").astype(float).drop(columns=f"{c}={base[c]}")
                   for c in cats], axis=1)
    y, g = df["log_price"].astype(float), df[group]
    Xd, yd = X - X.groupby(g).transform("mean"), y - y.groupby(g).transform("mean")
    Xd = Xd.loc[:, Xd.abs().sum() > 0]
    if g.nunique() > 1:
        m = sm.OLS(yd.values, Xd.values).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(g)[0]})
    else:
        m = sm.OLS(yd.values, Xd.values).fit(cov_type="HC1")
    ci = m.conf_int()
    t = pd.DataFrame({"term": Xd.columns, "pct": np.exp(m.params) - 1,
                      "lo": np.exp(ci[:, 0]) - 1, "hi": np.exp(ci[:, 1]) - 1})
    t[["variable", "level"]] = t["term"].str.split("=", n=1, expand=True)
    resid = pd.Series(yd.values - Xd.values @ m.params, index=df.index)
    return t, 1 - (resid ** 2).sum() / ((y - y.mean()) ** 2).sum(), resid


MAIN_SPEC = (["type_tenure", "new_build_name", "street_type", "month", "crime_quartile"],
             {"type_tenure": "Flat · leasehold", "new_build_name": "Existing", "street_type": "Road",
              "month": "2025-01", "crime_quartile": "Q1 lowest"})
FLAT_SPEC = (["floor_level", "building_type", "new_build_name", "street_type", "month", "crime_quartile"],
             {"floor_level": "Not stated", "building_type": "Numbered only", "new_build_name": "Existing",
              "street_type": "Road", "month": "2025-01", "crime_quartile": "Q1 lowest"})


def price_index(premiums: pd.DataFrame) -> pd.DataFrame:
    idx = premiums[premiums["variable"] == "month"][["level", "pct", "lo", "hi"]].rename(columns={"level": "month"})
    first = pd.DataFrame([{"month": "2025-01", "pct": 0.0, "lo": 0.0, "hi": 0.0}])
    return pd.concat([first, idx]).sort_values("month").reset_index(drop=True)


def comps_predict(train, test, levels, min_n=5):
    """Comparable-sales baseline: median log price of the same type in the finest area with min_n sales."""
    pred = pd.Series(np.nan, index=test.index)
    for lvl in levels:
        keys = [lvl, "type_name"] if lvl else ["type_name"]
        st = train.groupby(keys)["log_price"].agg(["median", "size"])
        st = st.loc[st["size"] >= min_n, "median"]
        idx = pd.MultiIndex.from_frame(test[keys]) if len(keys) > 1 else test[keys[0]]
        pred = pred.fillna(pd.Series(st.reindex(idx).values, index=test.index))
    return pred


def accuracy(actual_log, pred_log):
    ape = np.abs(np.exp(pred_log - actual_log) - 1)
    return {"MdAPE": ape.median(), "Within ±10%": (ape <= 0.10).mean(), "Within ±20%": (ape <= 0.20).mean()}


LADDER = [("No location", [None]), ("London region", ["london_part", None]), ("Borough", ["borough", None]),
          ("Postcode district", ["pc_district", "borough", None]),
          ("Postcode sector", ["pc_sector", "pc_district", "borough", None]),
          ("LSOA", ["lsoa_code", "pc_sector", "pc_district", "borough", None])]
SPLIT_DATE = "2025-11-01"


def granularity_ladder(df):
    train, test = df[df["date"] < SPLIT_DATE], df[df["date"] >= SPLIT_DATE]
    rows = []
    for label, chain in LADDER:
        acc = accuracy(test["log_price"], comps_predict(train, test, chain))
        rows.append({"level": label, "R² in-sample": fe_r2(df, "type_tenure", chain[0]), **acc})
    return pd.DataFrame(rows)


def baseline_test(df):
    train, test = df[df["date"] < SPLIT_DATE], df[df["date"] >= SPLIT_DATE].copy()
    pred = comps_predict(train, test, LADDER[-1][1])
    test["pred_price"] = np.exp(pred)
    test["ape"] = np.abs(np.exp(pred - test["log_price"]) - 1)
    return test


def morans_i(values, lat, lon, k=8):
    xy = np.column_stack([np.radians(lat), np.radians(lon) * np.cos(np.radians(51.5))])
    _, idx = NearestNeighbors(n_neighbors=k + 1).fit(xy).kneighbors(xy)
    z = values - values.mean()
    return (z * z[idx[:, 1:]].mean(axis=1)).sum() / (z ** 2).sum()


def spatial_check(df):
    cats, base = ["type_tenure", "new_build_name", "street_type", "month"], {k: v for k, v in MAIN_SPEC[1].items() if k != "crime_quartile"}
    tmp = df.assign(_all="London")
    out, resid_maps = [], {}
    for label, grp in [("No location", "_all"), ("Borough", "borough"), ("Postcode district", "pc_district"),
                       ("Postcode sector", "pc_sector")]:
        _, _, r = hedonic(tmp, cats, base, grp)
        g = tmp.assign(r=r).groupby("lsoa_code").agg(r=("r", "mean"), lat=("latitude", "mean"),
                                                     lon=("longitude", "mean"), n=("r", "size"))
        g = g[g["n"] >= 5]
        out.append({"controls": label, "Moran's I": morans_i(g["r"].values, g["lat"].values, g["lon"].values)})
        if label in ("No location", "Postcode sector"):
            resid_maps[label] = g.reset_index()
    return pd.DataFrame(out), resid_maps


# ---------------------------------------------------------------- valuation tool
def value_home(df, index, postcode, type_name, new_build_premium=None, min_n=5):
    """Estimate a price from comparable sales, time-adjusted to the latest month with the hedonic index."""
    pc = postcode.upper().strip()
    if " " not in pc and len(pc) >= 5:
        pc = pc[:-3] + " " + pc[-3:]
    adj = index.set_index("month")["pct"]
    latest = np.log1p(adj.iloc[-1])
    hit = df[df["postcode"] == pc]
    areas = []
    if len(hit):
        row = hit.iloc[0]
        areas = [("LSOA", "lsoa_code", row["lsoa_code"]), ("postcode sector", "pc_sector", row["pc_sector"]),
                 ("postcode district", "pc_district", row["pc_district"]), ("borough", "borough", row["borough"])]
    else:
        sector, district = pc[:-2].strip(), pc.split()[0] if " " in pc else pc
        areas = [("postcode sector", "pc_sector", sector), ("postcode district", "pc_district", district)]
    for label, col, val in areas:
        comps = df[(df[col] == val) & (df["type_name"] == type_name)]
        if len(comps) >= min_n:
            comps = comps.assign(adj_log=comps["log_price"] + latest - np.log1p(comps["month"].map(adj)))
            est = np.exp(comps["adj_log"].median())
            lo, hi = np.exp(comps["adj_log"].quantile([0.25, 0.75]))
            if new_build_premium is not None:
                est, lo, hi = est * (1 + new_build_premium), lo * (1 + new_build_premium), hi * (1 + new_build_premium)
            return {"estimate": est, "low": lo, "high": hi, "level": label, "area": val, "n": len(comps),
                    "spread": (hi - lo) / est, "borough": comps["borough"].mode().iloc[0],
                    "comps": comps.sort_values("date", ascending=False)}
    return None
