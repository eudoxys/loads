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

## Peak targets
`peak_target.csv` holds the monthly CAISO and WECC peak targets (MW) used by `loads.calibrate.Calibrate`
(`loads/_test/test_calibrate.py`, `loads/_validate/validate_calibrate.py`), derived from
`WECC_CAISO_hourly_load_2018-2022.csv`:
- each value is the maximum of `CAISO_load_MW` or `WECC_load_MW` over the month;
- rows are indexed by UTC month start, matching the calibration's UTC monthly blocks. Hours are converted
  from `utc_hour_ending` to UTC hour beginning (the model's convention) before grouping;
- rows cover 2018-01 to 2022-12. January 2018 lacks its first 8 UTC hours (PST 2017-12-31 16:00–23:00),
  which the source files do not include.

The WECC target is the US BA sum, which matches the 13-state WECC county membership in `state_groups.csv`
(no Canada or Mexico). The monthly WECC peak includes filled PSEI hours in most 2018 and 2020 months
(about 0.6–11 GW at the peak hour, typically 3–5 GW); no monthly CAISO peak hour was filled.

## CAISO membership
`state_groups.csv` gives each county's CAISO and WECC membership (0 to 1). Counties served by balancing
authorities other than CAISO are set from what serves them (2020 EIA-930 demand), not fitted to CAISO energy:
- Los Angeles 0.66: 1 − LDWP demand (26.4 TWh; LADWP, Burbank and Glendale) / Los Angeles' 2020 calibrated
  net load (77.7 TWh).
- Riverside 0.87: 1 − (55% of IID's demand, 3.82 TWh) / Riverside's calibrated net load (16.18 TWh). 55% is
  IID's share of customers in Riverside County (2018); the rest of IID is in Imperial County, outside CAISO.
- Sacramento 0: served by SMUD (BANC), whose service area covers the county (calibrated net load 10.4 TWh).
- Stanislaus 0: served by TID (TIDC, 2.84 TWh) and Modesto ID (BANC), which together exceed the county's
  calibrated net load (3.85 TWh); PG&E serves only rural pockets.

With these shares the CAISO-region net load is expected to be about 5.5% below CAISO's reported 2020 energy, about the size of
transmission and distribution losses, which CAISO's demand includes and the state energy targets may not.
Placer (Roseville, BANC), Shasta (Redding, BANC), Merced (TID) and San Joaquin (Modesto ID) are also partly
outside CAISO but remain full members.

## Distributed generation
The calibration and validation use `loads/wecc/county_dg_scaled.csv.gz`, built by `loads/wecc/county_dg_scale.py`
from `loads/wecc/county_dg.csv`:
- the 39 WECC counties missing from `county_dg.csv` (e.g., Kern, San Bernardino, Ada, Canyon, Bernalillo,
  Clackamas) get their state's DG profile in proportion to their share of the state's 2020 gross load;
- each state's DG is scaled, year by year, to EIA's estimated small-scale solar generation
  (`loads/wecc/eia_smallscale_pv.csv`, Electric Power Annual Table 3.21, all sectors), times the WECC share of
  the state for Texas (El Paso) and South Dakota (Custer, Fall River, Lawrence) by 2020 Census population.

The factors are in `loads/wecc/county_dg_scaling.csv`. `county_dg.csv` has no year-to-year growth, so the
factors rise each year; for 2020 California's is 3.18 (5.48 to 17.41 TWh, peak about 8.5 GW).

