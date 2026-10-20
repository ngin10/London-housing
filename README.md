# London Property Prices

An end-to-end pipeline and price model for London residential property sales, built on
**HM Land Registry Price Paid Data**, enriched with **postcode-level** location and
(optionally) EPC features.

## Data

`data/raw/london_sales_final.csv` contains **69,281 London sales (Jan 2025 – Jan 2026)**
from HM Land Registry Price Paid Data, already joined with postcode coordinates, LSOA,
and 12-month crime and burglary counts (`crimes_12m`, `burglaries_12m`). After keeping
standard residential sales (category A, excluding "Other" property types), **55,035**
sales remain.

The pipeline can also rebuild a dataset from raw Land Registry files
(`src/download.py` + postcodes.io geocoding) if the CSV is not present.

## Exploratory analysis

[`notebooks/London_Property_EDA.ipynb`](notebooks/London_Property_EDA.ipynb) is a full
EDA written from a valuation and model-risk perspective: a data-quality funnel, the
effect of the April 2025 stamp duty change, hedonic regression with postcode-sector fixed
effects, a mix-adjusted price index, spatial autocorrelation of residuals (Moran's I),
tax-threshold bunching, a comparable-sales baseline and outlier screening. Its findings
are summarised at the top of the notebook.

## Approach

1. **Download** yearly Price Paid files from HM Land Registry.
2. **Clean**: keep Greater London, standard sales (category A), residential property
   types, sensible price range; normalise postcodes and derive outward code / sector.
3. **Enrich at postcode level**:
   - Geocode every unique postcode via the [postcodes.io](https://postcodes.io) bulk API
     (lat/long, LSOA, MSOA, ward), cached locally.
   - *Optional*: aggregate EPC certificates to postcode level (median floor area, rooms,
     mean energy rating). Postcode-level aggregation was chosen over address-level EPC
     matching, which is slow and error-prone because of inconsistent address formats.
4. **Features**: property type, tenure, new build, borough, outward code, location,
   crime and burglary counts, time trend, and **leakage-safe** rolling 6-month median prices for each postcode
   sector and outward code (only prior months are used).
5. **Model**: LightGBM on log price, evaluated on a **time-based holdout** (the most
   recent months) against a sector-median baseline.

## Project structure

```
├── src/
│   ├── config.py          # paths, URLs, constants
│   ├── download.py        # fetch Land Registry yearly files
│   ├── clean.py           # filtering and cleaning
│   ├── geo.py             # postcodes.io geocoding + EPC postcode aggregation
│   ├── features.py        # feature engineering
│   ├── build_dataset.py   # raw -> processed parquet
│   └── train.py           # model training and evaluation
├── notebooks/
│   └── London_Property_EDA.ipynb   # full exploratory analysis
├── tests/
│   └── test_clean.py
├── data/raw/              # downloaded files (git-ignored)
├── data/processed/        # processed parquet (git-ignored)
└── outputs/               # metrics, model, figures (git-ignored)
```

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m src.build_dataset          # uses data/raw/london_sales_final.csv
python -m src.train --test-months 3
pytest
jupyter notebook notebooks/London_Property_EDA.ipynb
```

To build from raw Land Registry files instead:

```bash
python -m src.download --years 2023 2024 2025
python -m src.build_dataset          # add --no-geo to skip geocoding
```

**Optional EPC features:** register at <https://epc.opendatacommunities.org/>, download
domestic certificates for the London local authorities, combine them into
`data/raw/epc_certificates.csv`, and re-run `build_dataset`.

## Outputs

- `outputs/metrics.json`: MAE, MAPE, median APE, share of predictions within 10% / 20%,
  for both the model and the baseline
- `outputs/feature_importance.csv`
- `outputs/test_predictions.csv`

## Results

Time-based holdout: trained on Jan–Oct 2025 (45,012 sales), tested on
Nov 2025 – Jan 2026 (10,023 sales).

| Metric | LightGBM | Baseline (sector median) |
|---|---|---|
| Median absolute % error | **19.5%** | 32.4% |
| Within 10% of sale price | **27.1%** | 17.3% |
| Within 20% of sale price | **50.9%** | 33.1% |
| MAE | **£222k** | £334k |

The strongest features are location (lat/long), crime counts and the lagged sector price.
The main limitation is that there is no property size information: floor area is the
biggest driver of price, and adding postcode-level EPC floor area is the obvious next step.

## Data licences

Contains HM Land Registry data © Crown copyright and database right 2026, licensed under
the Open Government Licence v3.0. Postcode data from postcodes.io (ONS / OS open data).
