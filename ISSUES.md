# Issues log

Data and analysis issues found while building this project. Each one records the
evidence, the root cause, what was done about it, and what it changes for anyone using
the numbers.

| # | Issue | Severity | Status |
|---|---|---|---|
| 1 | A fifth of raw records aren't standard market sales | High | Resolved |
| 2 | Outer boroughs are only partly covered | High | Mitigated |
| 3 | The stamp duty deadline distorts monthly figures | High | Mitigated |
| 4 | Valuation error rises with property value | Medium | Open |
| 5 | Small numbers of invalid prices and postcodes | Low | Resolved |
| 6 | New areas have no price history for the baseline | Low | Mitigated |
| 7 | Cleaning rules and the data-quality report could drift apart | Low | Resolved |

---

### 1. A fifth of raw records aren't standard market sales

- **Evidence:** 14,189 of 69,281 raw records (20.5%) are Land Registry category B.
- **Root cause:** Category B covers repossessions, sales to companies, buy-to-lets
  identified by a mortgage, and transfers that aren't open-market sales. Their prices
  don't reflect what a home would sell for between private buyers and sellers.
- **Fix:** Keep category A only (`src/clean.py`, rule "Standard market sale").
- **Impact:** All figures describe ordinary open-market sales. Investor and repossession
  activity isn't covered, which should be stated wherever the figures are shown.

### 2. Outer boroughs are only partly covered

- **Evidence:** Sutton has 1 sale and Kingston upon Thames 23. Bexley and the City of
  London have under 200. Sutton's single sale has a Bromley-area postcode (SE20).
  94% of Hounslow's 494 sales are in W4 (Chiswick), so its median (£805k) is far
  above what the whole borough would show.
- **Root cause:** The source extract mainly covers London postal districts. Outer
  boroughs served by other postcode areas (KT, SM, TW, HA, UB and others) are mostly
  missing.
- **Fix:** Added `sales_count` and a `coverage` flag to `dim_borough`. The dashboard
  ranks boroughs with a measure that only counts "Reliable (300+ sales)" boroughs and
  shows a note on the borough page.
- **Impact:** Borough rankings are valid for the 25 reliable boroughs. Outer-borough
  figures describe the parts of the borough in the extract, not the whole borough.
- **Next step:** Rebuild from the full Land Registry files (`src/download.py`) to get
  complete coverage.

### 3. The stamp duty deadline distorts monthly figures

- **Evidence:** 10,087 sales completed in March 2025, 2.4× the January-February
  average. April fell to 1,715. The median price dropped to £540k in March, then
  jumped to £640k in April.
- **Root cause:** Stamp duty thresholds fell on 1 April 2025, so buyers rushed to
  complete in March. The rush was weighted towards cheaper homes, so the mix of
  homes sold changed. The price swing is mostly that mix change, not homes
  becoming cheaper and then dearer.
- **Fix:** The dashboard uses a rolling 3-month median and labels the change.
  The notebook builds a mix-adjusted price index (section 13): raw monthly moves of
  −8.5% / +8.5% shrink to −2.9% / +2.1% once property mix is held constant.
- **Impact:** Don't read month-on-month median changes around March-April 2025 as
  price changes. Model accuracy is tested on Nov 2025 to Jan 2026, well after the change.

### 4. Valuation error rises with property value

- **Evidence:** Median error is 16-17% for homes valued under £500k, 23% for
  £925k-£1.5m and 27% above £1.5m (holdout, 10,023 sales).
- **Root cause:** The data has no floor area or bedroom count. Size matters most for
  expensive homes, where two homes in the same street can differ hugely in size.
- **Status:** Open. The dashboard shows accuracy by value band so users can see it.
- **Next step:** Add postcode-level floor area from EPC certificates (`src/geo.py`
  already supports this once the EPC file is downloaded).

### 5. Small numbers of invalid prices and postcodes

- **Evidence:** 19 sales outside £10k-£20m, 25 malformed postcodes, 13 records outside
  Greater London. 7 more sales have valid postcodes that didn't geocode.
- **Fix:** Removed by cleaning rules. The 7 ungeocoded sales are kept but drop out of
  the map.
- **Impact:** Negligible: 57 records in 69,281 (0.08%).

### 6. New areas have no price history for the baseline

- **Evidence:** 4,221 sales (7.7%) have no previous-6-month median for their postcode
  sector. 4,048 of them are January 2025, the first month, which has no earlier
  months to look back on. The rest are in sectors with very few sales.
- **Fix:** The baseline falls back to the outward code, then to the London median.
  The model handles missing values directly.
- **Impact:** Small. Only 23 of the 10,023 test sales are affected.

### 7. Cleaning rules and the data-quality report could drift apart

- **Evidence:** The filtering was written as one combined condition, so there was no
  way to report how many rows each rule removed, and any separate funnel report would
  need the rules written twice.
- **Fix:** Cleaning rules are now one list (`RULES` in `src/clean.py`). Both `clean()`
  and `cleaning_funnel()` use it, and `export_powerbi` checks that the funnel's final
  count equals the number of rows exported.
- **Impact:** The data-quality page in the dashboard is always consistent with the data.
