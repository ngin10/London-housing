"""Download yearly HM Land Registry Price Paid files.

Usage:
    python -m src.download --years 2019 2020 2021 2022 2023 2024
"""
import argparse

import requests

from src.config import PPD_URL, RAW_DIR


def download_year(year: int, overwrite: bool = False) -> None:
    out = RAW_DIR / f"pp-{year}.csv"
    if out.exists() and not overwrite:
        print(f"[skip] {out.name} already exists")
        return
    url = PPD_URL.format(year=year)
    print(f"[get ] {url}")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        tmp = out.with_suffix(".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        tmp.rename(out)
    print(f"[done] {out.name} ({out.stat().st_size / 1e6:.0f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, nargs="+", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for year in args.years:
        download_year(year, args.overwrite)


if __name__ == "__main__":
    main()
