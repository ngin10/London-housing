"""Load raw Price Paid files and filter to clean London residential sales."""
from pathlib import Path

import pandas as pd

from src.config import (DURATION_MAP, LONDON_COUNTY, MAX_PRICE, MIN_PRICE,
                        PPD_COLUMNS, PROPERTY_TYPE_MAP, RAW_DIR,
                        SALES_COLUMN_MAP, SALES_FILE)


def normalise_postcode(pc: pd.Series) -> pd.Series:
    """Uppercase, strip, and enforce a single space before the inward code."""
    pc = pc.astype("string").str.upper().str.replace(r"\s+", "", regex=True)
    return pc.str[:-3] + " " + pc.str[-3:]


def load_raw(files: list[Path] | None = None) -> pd.DataFrame:
    files = files or sorted(RAW_DIR.glob("pp-*.csv"))
    if not files:
        raise FileNotFoundError(f"No pp-*.csv files in {RAW_DIR}. Run src.download first.")
    frames = []
    for f in files:
        # Filter each year to London while reading to keep memory low
        df = pd.read_csv(f, header=None, names=PPD_COLUMNS, dtype=str)
        frames.append(df[df["county"] == LONDON_COUNTY])
    return pd.concat(frames, ignore_index=True)


def load_sales_file(path: Path = SALES_FILE) -> pd.DataFrame:
    """Load the pre-joined sales file and rename columns to the PPD schema."""
    df = pd.read_csv(path, dtype={"unique_id": str, "paon": str, "saon": str})
    df = df.rename(columns=SALES_COLUMN_MAP)
    if "record_status" not in df:
        df["record_status"] = "A"
    return df


EXTRA_COLUMNS = ["latitude", "longitude", "lsoa_code", "crimes_12m", "burglaries_12m"]


POSTCODE_RE = r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$"

# Each cleaning rule: (label shown in the data-quality funnel, rows to keep).
# clean() and cleaning_funnel() both use this list, so the funnel always matches the data.
RULES = [
    ("Inside Greater London", lambda d: d["county"] == LONDON_COUNTY),
    ("Standard market sale (category A)", lambda d: d["ppd_category_type"] == "A"),
    ("Not a deleted record", lambda d: d["record_status"].fillna("A") != "D"),
    ("Residential property type", lambda d: d["property_type"] != "O"),
    (f"Price £{MIN_PRICE:,} to £{MAX_PRICE:,}", lambda d: d["price"].between(MIN_PRICE, MAX_PRICE)),
    ("Valid sale date", lambda d: d["date"].notna()),
    ("Valid postcode", lambda d: d["postcode"].str.match(POSTCODE_RE, na=False)),
    ("Not a duplicate transaction", lambda d: ~d["transaction_id"].duplicated()),
]


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["date"] = pd.to_datetime(df["date_of_transfer"], errors="coerce")
    df["postcode"] = normalise_postcode(df["postcode"])
    return df


def cleaning_funnel(df: pd.DataFrame) -> pd.DataFrame:
    """Row count after each cleaning rule, applied in order."""
    df = _prepare(df)
    steps = [("Raw records", len(df))]
    for label, rule in RULES:
        df = df.loc[rule(df)]
        steps.append((label, len(df)))
    out = pd.DataFrame(steps, columns=["step", "rows_remaining"])
    out["rows_removed"] = (-out["rows_remaining"].diff()).fillna(0).astype(int)
    out.insert(0, "step_order", range(len(out)))
    return out


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = _prepare(df)
    for _, rule in RULES:
        df = df.loc[rule(df)]

    df["property_type"] = df["property_type"].map(PROPERTY_TYPE_MAP)
    df["tenure"] = df["duration"].map(DURATION_MAP)
    df["new_build"] = (df["old_new"] == "Y").astype(int)
    df["borough"] = df["district"].str.title()
    df["outward_code"] = df["postcode"].str.split(" ").str[0]
    df["postcode_sector"] = df["postcode"].str[:-2]

    keep = ["transaction_id", "price", "date", "postcode", "outward_code",
            "postcode_sector", "property_type", "tenure", "new_build", "borough"]
    keep += [c for c in EXTRA_COLUMNS if c in df.columns]
    return df[keep].sort_values("date").reset_index(drop=True)
