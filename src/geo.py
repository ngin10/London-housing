"""Postcode-level enrichment.

1. Geocode unique postcodes via the postcodes.io bulk API (cached to parquet).
2. Optionally aggregate EPC certificates to postcode level (median floor area,
   modal energy rating) - avoids fragile address-level matching.
"""
import time

import pandas as pd
import requests

from src.config import EPC_FILE, POSTCODES_IO_BATCH, POSTCODES_IO_URL, PROCESSED_DIR

CACHE = PROCESSED_DIR / "postcode_lookup.parquet"
GEO_FIELDS = ["latitude", "longitude", "lsoa", "msoa", "admin_ward"]


def _lookup_batch(postcodes: list[str], session: requests.Session) -> list[dict]:
    for attempt in range(3):
        try:
            r = session.post(POSTCODES_IO_URL, json={"postcodes": postcodes}, timeout=30)
            r.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    rows = []
    for item in r.json()["result"]:
        res = item.get("result")
        row = {"postcode": item["query"]}
        row.update({k: (res or {}).get(k) for k in GEO_FIELDS})
        rows.append(row)
    return rows


def geocode_postcodes(postcodes: pd.Series) -> pd.DataFrame:
    """Return lookup table for all postcodes, using/refreshing the local cache."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    cached = pd.read_parquet(CACHE) if CACHE.exists() else pd.DataFrame(columns=["postcode", *GEO_FIELDS])
    todo = sorted(set(postcodes.dropna()) - set(cached["postcode"]))
    if todo:
        print(f"Geocoding {len(todo):,} new postcodes via postcodes.io ...")
        rows = []
        with requests.Session() as s:
            for i in range(0, len(todo), POSTCODES_IO_BATCH):
                rows += _lookup_batch(todo[i:i + POSTCODES_IO_BATCH], s)
                if (i // POSTCODES_IO_BATCH) % 50 == 0:
                    print(f"  {min(i + POSTCODES_IO_BATCH, len(todo)):,}/{len(todo):,}")
        cached = pd.concat([cached, pd.DataFrame(rows)], ignore_index=True)
        cached.to_parquet(CACHE, index=False)
    return cached


def epc_postcode_features() -> pd.DataFrame | None:
    """Aggregate EPC certificates to postcode level, if the file is present."""
    if not EPC_FILE.exists():
        print(f"[info] {EPC_FILE.name} not found - skipping EPC features")
        return None
    cols = ["POSTCODE", "TOTAL_FLOOR_AREA", "CURRENT_ENERGY_RATING", "NUMBER_HABITABLE_ROOMS"]
    epc = pd.read_csv(EPC_FILE, usecols=cols, dtype={"POSTCODE": str}, low_memory=False)
    from src.clean import normalise_postcode
    epc["postcode"] = normalise_postcode(epc["POSTCODE"])
    for c in ["TOTAL_FLOOR_AREA", "NUMBER_HABITABLE_ROOMS"]:
        epc[c] = pd.to_numeric(epc[c], errors="coerce")
    rating_score = {"A": 7, "B": 6, "C": 5, "D": 4, "E": 3, "F": 2, "G": 1}
    epc["epc_score"] = epc["CURRENT_ENERGY_RATING"].map(rating_score)
    return (
        epc.groupby("postcode")
        .agg(pc_median_floor_area=("TOTAL_FLOOR_AREA", "median"),
             pc_median_rooms=("NUMBER_HABITABLE_ROOMS", "median"),
             pc_mean_epc_score=("epc_score", "mean"),
             pc_epc_count=("epc_score", "size"))
        .reset_index()
    )
