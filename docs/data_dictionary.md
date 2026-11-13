# Data dictionary

The tables in `powerbi/data/`, produced by `python -m src.export_powerbi`. They form a
star schema: two fact tables, three dimension tables and one standalone table.

**Source:** HM Land Registry Price Paid Data, sales completed 1 Jan 2025 to 30 Jan 2026,
joined with postcodes.io coordinates and 12-month recorded crime counts per LSOA.

## fact_sales (55,035 rows, one per sale)

| Column | Type | Description | Cleaning / derivation |
|---|---|---|---|
| `transaction_id` | text | Land Registry unique ID | Key. Duplicates removed |
| `sale_date` | date | Date the sale completed (deed date) | Rows with no valid date removed. Completion lags the agreed sale by about 2-4 months |
| `price` | whole number, £ | Price paid | Kept £10,000 to £20,000,000 (19 rows outside this range removed) |
| `price_band` | text | Price band aligned to stamp duty thresholds from April 2025 | Bands: under £125k, £125k-£300k, £300k-£500k, £500k-£925k, £925k-£1.5m, £1.5m and over. Lower bound inclusive |
| `borough` | text | London borough (local authority) | Land Registry `district`, title-cased; "City of Westminster" shortened to "Westminster" |
| `property_type` | text | Flat/Maisonette, Terraced, Semi-detached, Detached | Land Registry code mapped to a name. "Other" removed |
| `tenure` | text | Freehold or Leasehold | |
| `new_build` | text | "New build" or "Existing" | From Land Registry old/new flag |
| `postcode` | text | Full postcode, e.g. `SW18 5PR` | Uppercased, single space; 25 invalid postcodes removed |
| `outward_code` | text | First half of the postcode, e.g. `SW18` | |
| `postcode_sector` | text | Outward code plus first inward digit, e.g. `SW18 5` | |
| `lsoa_code` | text | Census Lower Super Output Area (about 1,500 residents) | Blank for 7 sales whose postcode didn't geocode |
| `latitude`, `longitude` | decimal | Postcode centroid | Blank for the same 7 sales |
| `crimes_12m` | decimal | Recorded crimes in the sale's LSOA, previous 12 months | A count, not a rate per resident |
| `burglaries_12m` | decimal | Burglaries in the LSOA, previous 12 months | |

## fact_valuation_test (10,023 rows, one per holdout sale)

Valuations for sales from Nov 2025 to Jan 2026, made by a model trained only on
Jan-Oct 2025 (`python -m src.train`).

| Column | Type | Description |
|---|---|---|
| `transaction_id` | text | Links to `fact_sales` |
| `pred_price` | decimal, £ | LightGBM model valuation |
| `baseline_price` | decimal, £ | Simple benchmark: median price in the same postcode sector over the previous 6 months (falls back to outward code, then all London) |
| `model_ape` | decimal | Absolute % error of the model: \|pred − price\| / price |
| `baseline_ape` | decimal | Absolute % error of the baseline |
| `model_within_10pct` | 0/1 | 1 if the model is within 10% of the sale price |
| `model_within_20pct` | 0/1 | 1 if within 20% |
| `predicted_band` | text | Price band of the *predicted* price, so accuracy can be shown by value range |

## dim_date (395 rows, one per day)

| Column | Description |
|---|---|
| `date` | Calendar date (key; mark as date table in Power BI) |
| `year`, `month_number`, `quarter` | Calendar parts |
| `month_start` | First day of the month |
| `month_label` | e.g. "Mar 2025"; sort by `year_month` |
| `year_month` | e.g. "2025-03" |
| `weekday`, `weekday_number` | Monday = 1 |
| `sdlt_period` | "Before 1 Apr 2025" or "From 1 Apr 2025": the date stamp duty thresholds fell |

## dim_borough (29 rows)

| Column | Description |
|---|---|
| `borough` | Key |
| `inner_outer` | Inner or Outer London (ONS statistical definition) |
| `sales_count` | Sales in this extract |
| `coverage` | Reliable (300+ sales), Thin (100-299) or Too few (<100). See ISSUES.md #2 |

## dim_property_type (4 rows)

| Column | Description |
|---|---|
| `property_type` | Key |
| `type_order` | Sort order, flat to detached |
| `is_house` | "No" for flats, "Yes" otherwise |

## data_quality_funnel (9 rows)

Rows remaining after each cleaning rule in `src/clean.py`, applied in order.
`clean()` uses the same rule list, so the funnel always matches the data.

| Column | Description |
|---|---|
| `step_order` | 0 = raw extract |
| `step` | Rule name |
| `rows_remaining` | Rows left after this rule |
| `rows_removed` | Rows this rule removed |
