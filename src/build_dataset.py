"""Raw Price Paid files -> cleaned, geocoded, feature-ready parquet.

Uses data/raw/london_sales_final.csv if present (already geocoded, with
crime features). Otherwise falls back to raw pp-*.csv files from src.download.

Usage:
    python -m src.build_dataset            # geocode raw files via postcodes.io
    python -m src.build_dataset --no-geo   # skip geocoding (offline)
"""
import argparse

from src.clean import clean, load_raw, load_sales_file
from src.config import PROCESSED_DIR, SALES_FILE
from src.features import build_features
from src.geo import epc_postcode_features, geocode_postcodes

OUT = PROCESSED_DIR / "london_sales.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-geo", action="store_true")
    args = parser.parse_args()

    if SALES_FILE.exists():
        raw = load_sales_file()
        print(f"Loaded {SALES_FILE.name}: {len(raw):,} rows")
    else:
        raw = load_raw()
        print(f"Raw London rows: {len(raw):,}")
    df = clean(raw)
    print(f"After cleaning:  {len(df):,}")

    if not args.no_geo and "latitude" not in df.columns:
        lookup = geocode_postcodes(df["postcode"])
        df = df.merge(lookup, on="postcode", how="left")
        print(f"Geocoded: {df['latitude'].notna().mean():.1%} of sales")

    epc = epc_postcode_features()
    if epc is not None:
        df = df.merge(epc, on="postcode", how="left")
        print(f"EPC postcode match: {df['pc_median_floor_area'].notna().mean():.1%}")

    df = build_features(df)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.assign(month=df["month"].astype(str)).to_parquet(OUT, index=False)
    print(f"Saved {len(df):,} rows -> {OUT}")


if __name__ == "__main__":
    main()
