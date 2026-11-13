# What London homes sold for in 2025, and why

An end-to-end analysis of **55,035 London home sales** (HM Land Registry, January 2025 to
January 2026): from raw records through cleaning and validation to a **Power BI
dashboard**, an **Excel summary workbook**, a **stakeholder slide deck** and an
interactive **Streamlit app**.

**The question:** what does a typical London home sell for, what explains the
differences between homes and areas, and how far can an automated valuation be trusted?

<!-- Add dashboard screenshots here once built, e.g.
![Market overview](powerbi/screenshots/1_overview.png) -->

## Key findings

| | Finding | Evidence |
|---|---|---|
| 1 | **A stamp duty deadline distorted the year.** Buyers rushed to complete before thresholds fell on 1 April 2025. | 10,087 sales in March, **2.4×** the Jan-Feb average; April fell 83% to 1,715 |
| 2 | **Property type sets the price level.** A detached house typically costs 3.1× a flat. | Medians: flat £490k, terraced £790k, semi £890k, detached £1.51m |
| 3 | **Leasehold houses sell at a steep discount.** | **30-45%** below freehold houses of the same type |
| 4 | **Location spreads prices nearly threefold.** | Kensington and Chelsea £1.19m vs Bromley £420k (25 boroughs with 300+ sales) |
| 5 | **Automated valuations beat a simple benchmark, but struggle with expensive homes.** | Median error 19.5% vs 32.4% for the area median (40% lower); error rises from 16% under £300k to 27% above £1.5m |

Monthly median prices around March-April 2025 mostly reflect **which** homes sold,
not prices moving (see [ISSUES.md #3](ISSUES.md#3-the-stamp-duty-deadline-distorts-monthly-figures)).

## What's in this project

| Deliverable | What it shows | Tools |
|---|---|---|
| [Power BI dashboard](powerbi/) | 4 pages: market overview, borough comparison, stamp duty and price bands, data quality and model accuracy. Star-schema model and DAX measures | Power BI, DAX |
| [Excel workbook](reports/london_property_summary.xlsx) | Borough, monthly and property-type summaries, data-quality funnel with a reconciliation check, valuation accuracy. Every figure is a live formula over the raw sales table | Excel (COUNTIFS, AVERAGEIFS, AGGREGATE, conditional formatting, charts) |
| [Findings deck](reports/london_property_findings.pptx) | 8 slides for a non-technical audience, with speaker notes and editable charts | PowerPoint |
| [Issues log](ISSUES.md) | 7 data and analysis issues, each with evidence, root cause, fix and impact | |
| [Data dictionary](docs/data_dictionary.md) | Every column in every table, with how it was cleaned or derived | |
| [Price estimator app](app.py) | Deployed Streamlit app: estimate a home's price, market analytics, model transparency | Python, Streamlit, LightGBM |
| [Market explorer](explorer/) | Second Streamlit app: filters, maps, comparable-sales valuation, model checks | Python, Streamlit, Plotly |
| [EDA notebook](notebooks/London_Property_EDA.ipynb) | Full exploratory analysis plus advanced statistics (see below) | pandas, statsmodels |
| [Pipeline](src/) | Load, clean, enrich, build features, train and export; tested with pytest | Python |

## Data and data quality

**Source:** HM Land Registry Price Paid Data, joined with postcode coordinates
(postcodes.io) and 12-month crime counts per neighbourhood (LSOA).

Cleaning rules are defined once in [`src/clean.py`](src/clean.py) and logged as a
funnel, so every removed record is accounted for:

| Rule | Rows removed | Rows remaining |
|---|---:|---:|
| Raw records | | 69,281 |
| Outside Greater London | 13 | 69,268 |
| Not a standard market sale (category B: repossessions, company sales, other transfers) | 14,189 | 55,079 |
| Price below £10k or above £20m | 19 | 55,060 |
| Invalid postcode | 25 | **55,035** |

Three checks run on every export: transaction IDs are unique, every sale matches a
borough and property type in the dimension tables, and the funnel's final count equals
the rows exported.

**Known limitations** (full detail in [ISSUES.md](ISSUES.md)):
- Outer boroughs are only partly covered (Sutton has 1 sale, Kingston 23). Boroughs
  carry a coverage flag, and rankings use only those with 300+ sales.
- There's no floor area or bedroom count, which limits valuation accuracy for large homes.
- One year of data spanning a tax change, so seasonality can't be separated from the deadline effect.
- Crime figures are counts, not rates per resident.

## Valuation model

A LightGBM model on log price, trained on Jan-Oct 2025 and tested on the following three
months (10,023 sales it never saw). It's compared against a simple benchmark: the median
price in the same postcode sector over the previous six months.

| Metric | Model | Benchmark |
|---|---:|---:|
| Median absolute error | **19.5%** | 32.4% |
| Within 10% of sale price | **27.1%** | 17.3% |
| Within 20% of sale price | **50.9%** | 33.1% |

Area-level price features use only earlier months, so nothing from the test period leaks
into training.

## Advanced analysis (notebook)

[`notebooks/London_Property_EDA.ipynb`](notebooks/London_Property_EDA.ipynb) goes further:
hedonic regression with postcode-sector fixed effects (what each characteristic is
worth), a mix-adjusted price index, spatial autocorrelation of residuals (Moran's I),
tax-threshold bunching, a comparable-sales baseline at six levels of location detail,
and outlier screening.

## How to run

```bash
python -m venv .venv
.venv\Scripts\activate             # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

python -m src.build_dataset        # clean + features -> data/processed/
python -m src.train                # model + holdout predictions -> outputs/
python -m src.export_powerbi       # star schema CSVs -> powerbi/data/
python -m src.make_pbip            # Power BI project -> powerbi/london_property.pbip
python -m src.make_excel           # -> reports/london_property_summary.xlsx
python -m src.make_deck            # -> reports/london_property_findings.pptx
pytest

streamlit run app.py               # price estimator (deployed app)
streamlit run explorer/app.py      # market explorer
```

`make_excel` writes formulas without results: open the workbook in Excel and save it
once to calculate them (the committed copy is already calculated). Open
`powerbi/london_property.pbip` in Power BI Desktop and click Refresh to see the
dashboard (details in [`powerbi/README.md`](powerbi/README.md)).

## Project structure

```
├── src/
│   ├── config.py           paths, URLs, constants
│   ├── download.py         fetch Land Registry yearly files (optional rebuild)
│   ├── clean.py            cleaning rules and the data-quality funnel
│   ├── geo.py              postcode geocoding and optional EPC enrichment
│   ├── features.py         feature engineering (leakage-safe area prices)
│   ├── build_dataset.py    raw -> processed parquet
│   ├── train.py            model training and evaluation
│   ├── export_powerbi.py   star schema for Power BI and Excel
│   ├── make_pbip.py        Power BI project (model + report)
│   ├── make_excel.py       summary workbook
│   └── make_deck.py        findings deck
├── powerbi/                .pbip project, data/, measures.dax, guide
├── reports/                Excel workbook and PowerPoint deck
├── app.py                  Streamlit price estimator (deployed)
├── explorer/               Streamlit market explorer
├── notebooks/              exploratory analysis
├── docs/data_dictionary.md
├── ISSUES.md
└── tests/
```

## Data licences

Contains HM Land Registry data © Crown copyright and database right 2026, licensed under
the Open Government Licence v3.0. Postcode data from postcodes.io (ONS / OS open data).
