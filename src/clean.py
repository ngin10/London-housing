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


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["date"] = pd.to_datetime(df["date_of_transfer"], errors="coerce")
    df["postcode"] = normalise_postcode(df["postcode"])

    mask = (
        (df["county"] == LONDON_COUNTY)
        & (df["ppd_category_type"] == "A")      # standard price-paid sales only
        & (df["record_status"].fillna("A") != "D")          # drop deleted records
        & (df["property_type"] != "O")          # drop 'Other' (non-residential/mixed)
        & df["price"].between(MIN_PRICE, MAX_PRICE)
        & df["date"].notna()
        & df["postcode"].str.match(r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$", na=False)
    )
    df = df.loc[mask]
    df = df.drop_duplicates(subset="transaction_id")

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
