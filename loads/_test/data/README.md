# WECC and CAISO hourly load, 2018–2022

Source: U.S. EIA Form 930 "BALANCE" six-month files (www.eia.gov/electricity/gridmonitor/sixMonthFiles/),
2018 Jan–Jun through 2022 Jul–Dec, plus the first hour of 2023 Jan–Jun for Mountain-time BAs.
Retrieved 2026-10-19. Starting series: EIA's "Demand (MW) (Adjusted)".

## Files
- `WECC_CAISO_hourly_load_2018-2022.csv` — 43,824 hours
  - `utc_hour_ending`, `pst_hour_ending` (fixed UTC-8, no DST); covers PST 2018-01-01 01:00 to 2023-01-01 00:00
  - `WECC_load_MW` — sum of demand of the 28 US Western Interconnection BAs that report demand to EIA-930
    (EIA regions CAL, NW, SW). Excludes BC Hydro, AESO and CFE Baja California (EIA-930 has no demand for them)
    and generation-only BAs (AVRN, DEAA, GRID, GRIF, GRMA, GWA, HGMA, WWA), which have no load.
  - `CAISO_load_MW` — CISO demand, cleaned
  - `CAISO_EIA_reported_MW` — CISO "Demand (MW)" as originally reported, uncleaned
  - `WECC_BAs_filled`, `WECC_filled_MW`, `CAISO_filled` — how much of each hour was filled/estimated
- `WECC_BA_hourly_load_2018-2022.csv` — the cleaned per-BA series that sum to WECC_load_MW
- `WECC_BA_filled_flags_2018-2022.csv` — 1 where a BA-hour was filled

BAs: AVA AZPS BANC BPAT CHPD CISO DOPD EPE GCPD IID IPCO LDWP NEVP NWMT PACE PACW PGE PNM PSCO PSEI SCL SRP TEPC TIDC TPWR WACM WALC WAUW

## Cleaning
1. EIA adjusted values flagged bad if: an isolated single-hour spike (>30% off both neighbors),
   below 30% or above 200% of the centered 1-week median, or <= 0.
2. Missing/bad runs of <= 3 hours: linear interpolation.
3. Longer runs: BA's median share of the reference load (sum of BAs with complete data) for the same
   month and PST hour-of-day, times the reference load at that hour.

Largest gap: PSEI (Puget Sound Energy) has 12,884 missing hours, mostly Jul–Dec 2018 and Jan–Oct 2020.
Filled energy is 2.2% of WECC load in 2018, 3.6% in 2020, <0.3% in other years. CAISO needed 20 filled hours.

## Annual summary (PST calendar years)
| Year | WECC TWh | CAISO TWh | WECC peak MW | CAISO peak MW |
|---|---|---|---|---|
| 2018 | 729.2 | 225.6 | 139,370 | 46,133 |
| 2019 | 718.7 | 214.3 | 132,647 | 43,849 |
| 2020 | 718.1 | 218.0 | 140,778 | 46,643 |
| 2021 | 724.7 | 219.2 | 135,692 | 43,615 |
| 2022 | 744.1 | 223.7 | 143,047 | 51,104 |
