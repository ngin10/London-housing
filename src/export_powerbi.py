"""Export the cleaned data as a star schema of CSVs for Power BI (and Excel).

Run after build_dataset and train:
    python -m src.export_powerbi

Writes to powerbi/data/:
    fact_sales.csv           one row per sale (55k rows)
    dim_date.csv             one row per calendar day in the data's range
    dim_borough.csv          borough name and Inner/Outer London
    dim_property_type.csv    property type with a sort order
    fact_valuation_test.csv  model and baseline predictions for the holdout months
    data_quality_funnel.csv  rows remaining after each cleaning rule
"""
import numpy as np
import pandas as pd

from src.build_dataset import OUT as DATA_PATH
from src.clean import cleaning_funnel, load_sales_file
from src.config import OUTPUT_DIR, ROOT

OUT_DIR = ROOT / "powerbi" / "data"

# Stamp duty (SDLT) rates for home movers changed on 1 April 2025.
SDLT_CHANGE = pd.Timestamp("2025-04-01")

# ONS statistical definition of Inner London
INNER_LONDON = {
    "Camden", "City of London", "Hackney", "Hammersmith and Fulham", "Haringey",
    "Islington", "Kensington and Chelsea", "Lambeth", "Lewisham", "Newham",
    "Southwark", "Tower Hamlets", "Wandsworth", "Westminster",
}

# Price bands follow the SDLT thresholds that apply from April 2025:
# £125k (0% band ends), £300k (first-time buyer relief ends),
# £500k (first-time buyer relief cut-off), £925k (5% band ends), £1.5m (12% starts)
PRICE_BANDS = [0, 125_000, 300_000, 500_000, 925_000, 1_500_000, np.inf]
PRICE_BAND_LABELS = ["Under £125k", "£125k-£300k", "£300k-£500k",
                     "£500k-£925k", "£925k-£1.5m", "£1.5m and over"]

PROPERTY_TYPES = ["Flat/Maisonette", "Terraced", "Semi-detached", "Detached"]


def borough_name(s: pd.Series) -> pd.Series:
    """'City Of Westminster' -> 'Westminster', 'Kensington And Chelsea' -> 'Kensington and Chelsea'."""
    s = s.astype(str).str.replace(" And ", " and ").str.replace(" Of ", " of ").str.replace(" Upon ", " upon ")
    return s.replace({"City of Westminster": "Westminster"})


def price_band(price: pd.Series) -> pd.Series:
    return pd.cut(price, PRICE_BANDS, labels=PRICE_BAND_LABELS, right=False).astype(str)


def fact_sales(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "transaction_id": df["transaction_id"],
        "sale_date": df["date"].dt.date,
        "price": df["price"],
        "price_band": price_band(df["price"]),
        "borough": borough_name(df["borough"]),
        "property_type": df["property_type"].astype(str),
        "tenure": df["tenure"].astype(str),
        "new_build": np.where(df["new_build"] == 1, "New build", "Existing"),
        "postcode": df["postcode"].astype(str),
        "outward_code": df["outward_code"].astype(str),
        "postcode_sector": df["postcode_sector"],
        "lsoa_code": df["lsoa_code"],
        "latitude": df["latitude"],
        "longitude": df["longitude"],
        "crimes_12m": df["crimes_12m"],
        "burglaries_12m": df["burglaries_12m"],
    })


def dim_date(dates: pd.Series) -> pd.DataFrame:
    days = pd.date_range(dates.min(), dates.max(), freq="D")
    return pd.DataFrame({
        "date": days.date,
        "year": days.year,
        "month_number": days.month,
        "month_start": days.to_period("M").start_time.date,
        "month_label": days.strftime("%b %Y"),
        "year_month": days.strftime("%Y-%m"),   # sort key for month_label
        "quarter": "Q" + days.quarter.astype(str) + " " + days.year.astype(str),
        "weekday": days.day_name(),
        "weekday_number": days.dayofweek + 1,
        "sdlt_period": np.where(days < SDLT_CHANGE, "Before 1 Apr 2025", "From 1 Apr 2025"),
    })


def coverage(n: int) -> str:
    """How far a borough's figures can be trusted, given how many sales it has."""
    if n >= 300:
        return "Reliable (300+ sales)"
    if n >= 100:
        return "Thin (100-299 sales)"
    return "Too few (<100 sales)"


def dim_borough(boroughs: pd.Series) -> pd.DataFrame:
    """Borough attributes. sales_count and coverage describe this dataset's coverage,
    which is partial for outer boroughs (see ISSUES.md)."""
    counts = boroughs.value_counts().sort_index()
    return pd.DataFrame({
        "borough": counts.index,
        "inner_outer": ["Inner London" if x in INNER_LONDON else "Outer London" for x in counts.index],
        "sales_count": counts.values,
        "coverage": [coverage(n) for n in counts.values],
    })


def dim_property_type() -> pd.DataFrame:
    return pd.DataFrame({"property_type": PROPERTY_TYPES,
                         "type_order": range(1, len(PROPERTY_TYPES) + 1),
                         "is_house": ["No", "Yes", "Yes", "Yes"]})


def fact_valuation_test(df: pd.DataFrame) -> pd.DataFrame | None:
    """Holdout predictions from src.train, joined with the sector-median baseline."""
    path = OUTPUT_DIR / "test_predictions.csv"
    if not path.exists():
        print(f"[info] {path.name} not found - run src.train to add the accuracy table")
        return None
    t = pd.read_csv(path)[["transaction_id", "price", "pred_price"]]
    base = df.set_index("transaction_id")
    base = np.exp(base["postcode_sector_lag6m_log_price"]
                  .fillna(base["outward_code_lag6m_log_price"])
                  .fillna(df["log_price"].median()))
    t["baseline_price"] = t["transaction_id"].map(base)
    t["model_ape"] = (t["pred_price"] - t["price"]).abs() / t["price"]
    t["baseline_ape"] = (t["baseline_price"] - t["price"]).abs() / t["price"]
    t["model_within_10pct"] = (t["model_ape"] <= 0.10).astype(int)
    t["model_within_20pct"] = (t["model_ape"] <= 0.20).astype(int)
    t["predicted_band"] = price_band(t["pred_price"])
    return t.drop(columns="price")


def main() -> None:
    df = pd.read_parquet(DATA_PATH)
    df["date"] = pd.to_datetime(df["date"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sales = fact_sales(df)
    tables = {
        "fact_sales": sales,
        "dim_date": dim_date(df["date"]),
        "dim_borough": dim_borough(sales["borough"]),
        "dim_property_type": dim_property_type(),
        "data_quality_funnel": cleaning_funnel(load_sales_file()),
        "fact_valuation_test": fact_valuation_test(df),
    }

    # Checks that keep the model's relationships valid in Power BI
    assert sales["transaction_id"].is_unique
    assert set(sales["borough"]) <= set(tables["dim_borough"]["borough"])
    assert set(sales["property_type"]) <= set(PROPERTY_TYPES)
    assert tables["data_quality_funnel"]["rows_remaining"].iloc[-1] == len(sales)

    for name, t in tables.items():
        if t is not None:
            t.to_csv(OUT_DIR / f"{name}.csv", index=False)
            print(f"{name:22s} {len(t):>7,} rows")
    print(f"Saved to {OUT_DIR}")


if __name__ == "__main__":
    main()
