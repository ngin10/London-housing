"""Feature engineering for the price model.

All area-level price features use only sales from *previous* months,
so they are safe to use with a time-based train/test split.
"""
import numpy as np
import pandas as pd

CATEGORICAL = ["property_type", "tenure", "borough", "outward_code"]


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["month"] = df["date"].dt.to_period("M")
    df["months_since_start"] = (df["month"] - df["month"].min()).apply(lambda x: x.n)
    df["sale_month_of_year"] = df["date"].dt.month
    return df


def add_lagged_area_price(df: pd.DataFrame, level: str = "postcode_sector",
                          window: int = 6) -> pd.DataFrame:
    """Rolling median log-price of an area over the previous `window` months."""
    df = df.copy()
    df["log_price"] = np.log(df["price"])
    monthly = (df.groupby([level, "month"])["log_price"].median()
                 .rename("m").reset_index())

    all_months = pd.period_range(df["month"].min(), df["month"].max(), freq="M")
    out = []
    for area, g in monthly.groupby(level):
        s = g.set_index("month")["m"].reindex(all_months)
        lagged = s.shift(1).rolling(window, min_periods=1).mean()
        out.append(pd.DataFrame({level: area, "month": all_months,
                                 f"{level}_lag{window}m_log_price": lagged.values}))
    lag = pd.concat(out, ignore_index=True)
    return df.merge(lag, on=[level, "month"], how="left")


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = add_time_features(df)
    df = add_lagged_area_price(df, "postcode_sector")
    df = add_lagged_area_price(df, "outward_code")
    df = df.drop(columns="log_price")
    df["log_price"] = np.log(df["price"])
    for c in CATEGORICAL:
        df[c] = df[c].astype("category")
    return df


def feature_columns(df: pd.DataFrame) -> list[str]:
    numeric = ["new_build", "months_since_start", "sale_month_of_year",
               "latitude", "longitude",
               "postcode_sector_lag6m_log_price", "outward_code_lag6m_log_price",
               "crimes_12m", "burglaries_12m"]
    optional = ["pc_median_floor_area", "pc_median_rooms",
                "pc_mean_epc_score", "pc_epc_count"]
    return CATEGORICAL + [c for c in numeric + optional if c in df.columns]
