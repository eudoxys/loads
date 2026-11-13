Validation
----------

## Estimator

The `validate_estimator_marimo.py` notebook validates the choice of holdout
and harmonics of `loads.estimator.Estimator` on individual counties. Run the
marimo notebook

	marimo run validate_estimator_marimo.py

## Energy and peak calibration (`CalibrateEnergyPeak`)

The `validate_calibrate_marimo.py` notebook compares the CAISO-region net
load of the calibrated 2020 WECC county loads with the hourly load CAISO
reported for 2020 (`loads/caiso/2020.csv`). The calibration uses the default
settings of `loads/_explore/explore_calibrate_marimo.py`, i.e., the
predeclared weight search and selection rule of `loads.calibrate.CalibrateEnergyPeak`
with the targets and memberships in `loads/_test/data`, applied month by
month. Build the 2020 load matrix and the calibration in the local cache
first (407 county predictions and 12 monthly weight searches)

	python validate_calibrate.py

then run the marimo notebook

	marimo run validate_calibrate_marimo.py

### Inputs

All loads are hourly, indexed by UTC hour beginning. Calibration blocks are
UTC calendar months.

| Input | File | Basis |
| ----- | ---- | ----- |
| Gross county load $X$ | cache `loads/0/_validate/calibrate_X_2020.csv.gz` | TSGAM prediction of `elec_total_MW` for each of the 407 WECC counties with 2020 weather; excludes rooftop PV |
| Rooftop PV (DG) $D$ | `loads/wecc/county_dg.csv.gz` | unscaled county rooftop PV output (MW, positive); counties missing from it have no DG (see below) |
| State energy targets | `loads/_test/data/energy_target.csv` | monthly net-load energy (MWh) of the 13 WECC states |
| Regional peak targets | `loads/_test/data/peak_target.csv` | monthly CAISO and WECC peak demand (MW) from EIA-930 (see below) |
| Region membership | `loads/_test/data/state_groups.csv` | each county's CAISO and WECC membership, 0 to 1 (see below) |
| Validation reference | `loads/caiso/2020.csv` | CAISO reported hourly load, Pacific prevailing time, hour ending |

**Peak targets.** `peak_target.csv` holds each UTC month's maximum hourly
demand of CAISO and of the 28 US Western Interconnection balancing
authorities (BAs), from the cleaned EIA-930 series in
`loads/_test/data/WECC_CAISO_hourly_load_2018-2022.csv` (2018-01 to
2022-12). The WECC target excludes BC Hydro, AESO and CFE Baja California,
matching the 13-state US county membership. EIA-930 demand is load served
from the grid, so it is net of rooftop PV and includes transmission and
distribution losses. See `loads/_test/data/README.md`.

**CAISO membership.** County boundaries do not follow BA boundaries, so
counties served by non-CAISO BAs are set from what serves them, using 2020
EIA-930 demand:

| County | CAISO share | Reason |
| ------ | ----------- | ------ |
| Los Angeles | 0.66 | excludes the LADWP BA (LADWP, Burbank, Glendale; 26.4 TWh) |
| Riverside | 0.87 | excludes the IID Coachella Valley load (55% of IID's 3.82 TWh) |
| Sacramento | 0 | SMUD (BANC) |
| Stanislaus | 0 | TID (TIDC) and Modesto ID (BANC) |
| Alpine, Del Norte, Imperial, Inyo, Lassen, Modoc, Mono, Siskiyou | 0 | not served by CAISO |

Placer (Roseville, BANC), Shasta (Redding, BANC), Merced (TID) and San
Joaquin (Modesto ID) are partly outside CAISO but remain full members.

**Rooftop PV.** Testing, validation and review use the unscaled
`loads/wecc/county_dg.csv.gz` (the compressed `county_dg.csv`). It has about
a third of EIA's estimated California small-scale solar generation, no
year-to-year growth, and no DG for 39 WECC counties (e.g., Kern, San
Bernardino, Ada, Canyon, Bernalillo, Clackamas), which therefore have no DG.
`loads/wecc/county_dg_scale.py` also builds an EIA-scaled
`county_dg_scaled.csv.gz` from it, which is not used here:

1. Each missing county gets its state's DG profile in proportion to its
   share of the state's 2020 gross load.
2. Each state's DG is scaled, year by year, so its annual energy equals EIA's
   estimated small-scale solar generation (`loads/wecc/eia_smallscale_pv.csv`,
   Electric Power Annual Table 3.21, all sectors, 2018-2022), times the WECC
   share of the state for Texas (El Paso) and South Dakota (Custer, Fall
   River, Lawrence) by 2020 Census population.

The hourly shapes and the county distribution within each state are kept.
The factors are in `loads/wecc/county_dg_scaling.csv`; for 2020 California's
is 3.18 (5.48 to 17.41 TWh, peak about 8.5 GW).

### Procedure

1. **Gross load.** `validate_calibrate.gross_load()` predicts $X$ for every
   WECC county and caches it; negative predictions are clipped to zero.
2. **DG.** `validate_calibrate.distributed_generation()` aligns
   `county_dg.csv.gz` with $X$.
3. **Calibration.** `validate_calibrate.calibrated_load()` runs
   `CalibrateEnergyPeak(X,dg=D,energy=...,peak=...,regions=...,search=True)`. For each
   UTC month it finds a per-county scale and offset of the gross load so
   that the shaped net load $L-D$ meets each state's energy target and
   reaches, without exceeding, the CAISO and WECC peak targets, where the
   regional net load is $\sum_j g_j(L_{tj}-D_{tj})$ with $g_j$ the county's
   membership. It searches the predeclared 88-point weight grid and applies
   the selection rule. Results are cached (cache version 1, so results
   computed with the scaled DG, version 0, are not reused) as `calibrate_L_2020.csv.gz`,
   `calibrate_summary_2020.csv`, `calibrate_regions_2020.csv` and
   `calibrate_states_2020.csv`.
4. **Comparison.** The notebook compares the CAISO-region net load of the
   calibrated load, $\sum_j g_j(L_{tj}-D_{tj})$, and of the uncalibrated
   prediction, $\sum_j g_j(X_{tj}-D_{tj})$, with the CAISO reported load,
   which is net of rooftop PV. CAISO hour-ending Pacific times are converted
   to UTC hour beginning, and only hours common to both are compared. It
   reports energy and peak error, MAPE, CV(RMSE), bias, R² and correlation,
   overall and by month, and the average daily profiles.

The same inputs drive `loads/_test/test_calibrate.py`, which calibrates
August 2020 only.

### Results (2020)

All 12 months pass the selection tolerances, every state's energy is within
0.5% of its target, and the CAISO and WECC peaks reach their targets. Fit of
the CAISO-region net load to the CAISO reported load over 8,776 hours, with
the unscaled `county_dg.csv` DG (CAISO-region DG 4.4 TWh, peak 2.1 GW), now
used by the validation, and, for reference, the EIA-scaled DG (15.5 TWh,
7.5 GW) used before. These results were produced before the switch to the
unscaled DG and have not been re-run since (`validate_calibrate.py` needs
NSRDB weather and takes hours on an empty cache):

| Model | Energy error | Peak error | MAPE | CV(RMSE) | R² | Correlation |
| ----- | ------------ | ---------- | ---- | -------- | -- | ----------- |
| TSGAM input, unscaled DG | +25.7% | +21.7% | 26.7% | 31.5% | −1.44 | 0.775 |
| **Calibrated, unscaled DG** | **−3.8%** | **−0.7%** | **14.5%** | **17.1%** | **0.28** | **0.771** |
| TSGAM input, scaled DG | +20.7% | +15.3% | 21.6% | 24.4% | −0.47 | 0.854 |
| Calibrated, scaled DG | −3.7% | −0.7% | 11.2% | 13.9% | 0.53 | 0.844 |

With the scaled DG, the calibrated net load reproduces the reported midday
dip and is
within about 1.6 GW of the reported load between 10:00 and 16:00 Pacific in
April and August. The largest remaining errors are at night, when the
calibrated load is about 2–5 GW (April) and 8–10 GW (August) below the
reported load between midnight and 04:00 Pacific,
and in February, August and November, whose energy is 11–14% low. The peak
error is the difference between the EIA-930 CAISO peak target and the peak in
`loads/caiso/2020.csv`.

Counties with negative net load (default, 2018–2022):

| County | Negative hours | Minimum MW | Mean MW | PV peak MW | Gross estimate mean MW |
| ------ | -------------- | ---------- | ------- | ---------- | ---------------------- |
| Amador CA | 14,870 | −428 | 19 | 536 | 175 |
| Garfield UT | 8,372 | −23 | 13 | 41 | 17 |
| Tehama CA | 866 | −34 | 75 | 88 | 115 |
| Kane UT | 232 | −3 | 13 | 15 | 14 |
| Mariposa CA | 1 | −0.3 | 12 | 9 | 18 |

Amador CA's PV peaks at three times its mean gross load, which looks like a
DG data error (also noted in PR #62). Calibration lowers California's gross
load (CISO's scale is below one), which makes PV-heavy CISO counties more
negative.

### Known gaps

- **Losses.** Peak targets and the CAISO reference include transmission and
  distribution losses. The state energy targets are not adjusted for losses,
  so the calibrated regional energy may fall short of the reported energy by
  about the loss rate (EIA estimates about 5% nationally).
- **DG.** The unscaled DG is about a third of EIA's estimated small-scale
  solar generation in California and is missing for 39 counties, so the
  midday net load is too high (R² 0.28 against 0.53 with the scaled DG).
  Errors in its energy, hourly shape or county distribution appear directly
  as net-load errors in daylight hours.
- **Membership.** Shares are annual and based on 2020; partly non-CAISO
  counties listed above remain full members.

## Peak and trough calibration (`CalibratePeaks`)

The `validate_calibrate_peaks_marimo.py` notebook validates the WECC240 node
load in `loads/wecc/node_total.csv.gz`, made by
`loads/_review/review_wecc_calibrate_eia930_marimo.py`, which calibrates each
US WECC BA's share of the county net loads to the BA's EIA-930 monthly
maximum and minimum with `loads.calibrate.CalibratePeaks` (peak 1.0, trough
0.0). Run the marimo notebook

	marimo run validate_calibrate_peaks_marimo.py

and pick a year, a month and a BA (none for all of WECC), as in
`loads/_review/review_node_total_marimo.py`.

- **Calibrated net load:** `node_total.csv.gz` is total (gross) load, while
  EIA-930 demand is net of rooftop PV. So the notebook subtracts the county
  rooftop PV of `loads/wecc/county_dg.csv.gz`, unscaled as in the
  calibration and allocated to nodes with `loads/wecc/node_estimate_cf.csv`.
- **A BA:** its calibrated net load, `loads/wecc/ba_net.csv.gz` (the sum of
  its calibrated county shares, saved from the review notebook), against its
  reported demand in `loads/_test/data/WECC_BA_hourly_load_2018-2022.csv`.
  The plotted total adds the BA's share of the county rooftop PV, using the
  factors in `loads/wecc/county_ba.csv`.
- **Reported demand for WECC:** the hourly `WECC_load_MW` of
  `loads/_test/data/WECC_CAISO_hourly_load_2018-2022.csv`, the sum of the 28
  US WECC BAs.
- **Metrics:** MAPE, MAE, RMSE, R² and total energy error of the
  calibrated net load against reported demand, over the hours shown.

### Results

WECC (calibrated net load of all WECC counties):

| Period | Hours | MAPE (%) | MAE (MW) | RMSE (MW) | R² | Energy error (%) | Peak (MW) | Reported peak (MW) |
| ------ | ----: | -------: | -------: | --------: | -: | ---------------: | --------: | -----------------: |
| 2018–2022 | 43,816 | 5.43 | 4,526 | 5,629 | 0.832 | −0.74 | 146,188 | 143,047 |
| 2018 | 8,752 | 4.44 | 3,709 | 4,623 | 0.886 | −0.75 | 140,346 | 139,370 |
| 2019 | 8,760 | 5.50 | 4,536 | 5,578 | 0.826 | −1.34 | 134,577 | 132,647 |
| 2020 | 8,784 | 5.60 | 4,572 | 5,648 | 0.838 | +0.04 | 141,026 | 140,778 |
| 2021 | 8,760 | 5.41 | 4,514 | 5,601 | 0.832 | −0.70 | 139,823 | 135,692 |
| 2022 | 8,760 | 6.20 | 5,298 | 6,530 | 0.768 | −0.92 | 146,188 | 143,047 |
| Aug 2020 | 744 | 6.04 | 5,703 | 6,770 | 0.867 | −0.85 | 141,026 | 140,778 |

By BA, 2018–2022 (calibrated net load vs reported demand):

| BA | MAPE (%) | MAE (MW) | RMSE (MW) | R² | Energy error (%) |
| -- | -------: | -------: | --------: | -: | ---------------: |
| AVA | 6.46 | 95 | 125 | 0.771 | −3.72 |
| AZPS | 9.10 | 306 | 373 | 0.881 | −2.44 |
| BANC | 8.30 | 165 | 215 | 0.834 | +0.56 |
| BPAT | 5.39 | 351 | 467 | 0.770 | −2.52 |
| CHPD | 8.47 | 18 | 26 | 0.852 | −0.30 |
| CISO | 10.74 | 2,662 | 3,336 | 0.543 | +0.99 |
| DOPD | 6.97 | 14 | 18 | 0.878 | −0.83 |
| EPE | 6.41 | 61 | 82 | 0.923 | −1.29 |
| GCPD | 4.83 | 31 | 40 | 0.766 | −1.95 |
| IID | 10.60 | 42 | 59 | 0.906 | −3.39 |
| IPCO | 6.77 | 136 | 182 | 0.853 | −2.55 |
| LDWP | 10.26 | 311 | 397 | 0.647 | −0.40 |
| NEVP | 6.19 | 269 | 347 | 0.914 | +1.28 |
| NWMT | 6.21 | 86 | 121 | 0.576 | −3.90 |
| PACE | 4.96 | 274 | 357 | 0.825 | −1.24 |
| PACW | 7.18 | 170 | 223 | 0.733 | −2.80 |
| PGE | 6.56 | 160 | 208 | 0.764 | −0.17 |
| PNM | 4.89 | 77 | 97 | 0.857 | −0.59 |
| PSCO | 5.80 | 315 | 403 | 0.827 | −0.69 |
| PSEI | 8.96 | 266 | 381 | 0.685 | −4.56 |
| SCL | 6.18 | 68 | 92 | 0.801 | −2.91 |
| SRP | 6.37 | 237 | 318 | 0.926 | −3.40 |
| TEPC | 17.15 | 233 | 303 | 0.724 | −4.88 |
| TIDC | 8.04 | 26 | 33 | 0.859 | −4.46 |
| TPWR | 6.89 | 38 | 51 | 0.783 | −4.00 |
| WACM | 8.82 | 225 | 297 | 0.709 | −5.11 |
| WALC | 11.93 | 127 | 165 | 0.592 | −6.69 |
| WAUW | 10.32 | 10 | 12 | 0.585 | −6.46 |

Each BA matches its own reported monthly maximum and minimum, so the energy
error is small. The WECC peak is slightly high because BA peaks aren't
simultaneous, so matching each BA's maximum doesn't fix the sum's maximum.
The hourly shape errors (MAPE about 5–6%) come from the county estimates
within each month. They're larger for single BAs (5–17%) than for WECC
because BA errors partly cancel in the sum. CISO is notably weak (MAPE 10.7%,
R² 0.54): its model load is about 23% above its reported demand (see
`loads/_review/review_wecc_calibrate_eia930_marimo.py`), and the strong
monthly scale preserves the extremes but not the daily shape. Most BAs come
out below their reported energy (−7% to +1%), because a min/max fit doesn't
constrain energy.

## Hourly calibration to EIA-930 balancing authority demand (`CalibrateHourly`)

`validate_calibrate_hourly.py` checks `loads.calibrate.CalibrateHourly`
on the 2018–2022 WECC county estimate. It splits the hourly EIA-930 demand
of each of the 28 US WECC balancing authorities (BAs) that report demand
among the counties the BA serves, then allocates the counties to the WECC
240 load nodes. EIA-930 demand is net of rooftop PV, so each BA's gross
demand (demand plus the PV of its counties) is split in proportion to each
county's gross load contribution and the county's PV, which is fixed, is
subtracted. The calibrated net load is negative where the PV exceeds the
calibrated gross load. With `--clip`, the net load is instead clipped at
zero and calibrated without PV, which is the method of the node loads
published by `eudoxys/wecc240` (pull request #2). The PV is the unscaled
`loads/wecc/county_dg.csv.gz`; the EIA-scaled `county_dg_scaled.csv.gz` is
not used for this validation, its tests or the review notebooks. Because
`wecc240` used the scaled PV, the comparison with its node loads is
reported for information only.

	python validate_calibrate_hourly.py [--clip] --compare node_ba_load.csv.gz

where `node_ba_load.csv.gz` is `wecc240/data/node_ba_load.csv.gz` from that
pull request (omit `--compare` to skip the comparison). It takes about a
minute. Review the results with the marimo notebooks
`loads/_review/review_calibrated_nodes_marimo.py` (WECC240 nodes) and
`loads/_review/review_calibrated_counties_marimo.py` (counties by state,
with scale, offset, energy, peak and error statistics relative to the
estimate), which use the same inputs (`inputs()` in the script).

### Inputs

| Input | File | Basis |
| ----- | ---- | ----- |
| County gross load $G$ | `loads/wecc/wecc_estimate.csv.gz` | gross county estimate (calibrated) |
| Rooftop PV $P$ | `loads/wecc/county_dg.csv.gz` | unscaled county rooftop PV (fixed; 38 counties and the first 7 hours of 2018 have none); with `--clip`, $\max(G-P,0)$ is calibrated without PV |
| BA factors $f$ | `loads/wecc/county_ba.csv` | share of each county's load served by each BA, fitted to EIA-861 2018 sales (PR #62, in the package) |
| BA demand $D$ | `loads/_test/data/WECC_BA_hourly_load_2018-2022.csv` | cleaned EIA-930 demand, UTC hour-ending → hour-beginning (PR #62, in the package) |
| Node factors $g$ | `loads/wecc/node_estimate_cf.csv` | county → WECC 240 node factors (decision 16) |

The two PR #62 inputs are the files at commit `9341b13` the `wecc240` node
loads were built from.

### Results (2018–2022)

All 407 counties have factors; 29 BAs serve them, of which `SWPP` (border
counties) reports no WECC demand and keeps its estimated share
(2.96 TWh/y). 113 nodes receive load. The first 8 hours of 2018 are missing
from the source and are `NaN` for the counties of the missing BAs; the
other 43,816 hours are checked. The script prints `PASS`/`FAIL` for each
check and exits with status 1 if any fails:

| Check | Criterion | Result |
| ----- | --------- | ------ |
| 1. BA shares | county net shares $f_{ub}\left(G_u(D_b+P_b)/S_b-P_u\right)$, recomputed BA by BA from the inputs, sum to each BA's EIA-930 demand, and each county's BA shares sum to its `CalibrateHourly` load (same `NaN` hours); tolerance 10⁻⁶ MW | pass: 28 BAs, max error 4×10⁻¹¹ MW (shares vs demand), 7×10⁻¹² MW (shares vs county load) |
| 2. WECC total | county total − `SWPP` share = EIA-930 US WECC total `WECC_load_MW` (28 US BAs; BC Hydro, AESO and CFE excluded); tolerance 5 MW | pass: max 2 MW, mean −0.0004 MW (rounding of the per-BA series) |
| 3. US only | every county in a US state; no Canadian or Mexican BA (`AESO`, `BCHA`, `CFE`); node total = county total (10⁻⁶ MW) | pass: none; none; 3×10⁻¹⁰ MW |
| 4. Nonnegative gross | no negative calibrated county gross load (negative net load is reported) | pass: minimum gross 0.30 MW; negative net load in 24,341 county-hours (5 counties), no negative node load |
| 5. wecc240 | reported only (`INFO`): `wecc240` used the scaled PV and clips net load at zero | same 113 nodes and `NaN` hours; differs by up to 735 MW (627 MW with `--clip`) |

Checks 1–4 pass with and without `--clip`, and the annual energy below is
the same (the BA totals are matched either way; only the uncalibrated
`SWPP` share depends on the PV). Check 2 is independent of
the PR #62 inputs: `WECC_load_MW` is on `main`.
Node `c2u6xt` is in Canada but receives only the load of nearby US
counties; no Canadian or Mexican load is in the node totals.

| Year | EIA-930 TWh | County TWh | Node TWh | Node peak MW |
| ---- | ----------- | ---------- | -------- | ------------ |
| 2018 | 728.6 | 731.5 | 731.5 | 139,894 |
| 2019 | 718.7 | 721.7 | 721.7 | 133,136 |
| 2020 | 718.1 | 721.1 | 721.1 | 141,279 |
| 2021 | 724.7 | 727.6 | 727.6 | 136,199 |
| 2022 | 744.2 | 747.1 | 747.1 | 143,500 |

### Known gaps

- **Hourly shape.** Each BA's hourly demand is reproduced exactly; within a
  BA, the county shares follow the estimate's hourly shape. Errors in the
  relative shape of counties in the same BA are not corrected.
- **DG.** The rooftop PV is taken as given. Errors in it (e.g., Amador CA)
  move load between the counties of a BA without changing the BA total.
- **Factors.** BA factors are annual (EIA-861 2018) and constant in time.
- **Coverage.** BC Hydro, AESO and CFE report no demand to EIA-930, so
  Canadian and Mexican loads are not calibrated (and not in the county
  estimate).

## Energy-only calibration and `Calibrate`

`CalibrateEnergy` (proportional scaling to energy) and the `Calibrate`
front end (`CalibrateConfig` chooses one of the methods above for a single
`loads` frame) have no field validation of their own. `CalibrateEnergy`
matches its targets by construction; `loads/_test/test_calibrate_energy.py`
and `loads/_test/test_calibrate_config.py` check the energy match, the
fixed DG and the rebuilt total, sector and net columns on synthetic data.
The `wecc_estimate.csv.gz` monthly rescale (DESIGN decision 15) is the same
proportional calibration applied to every WECC county, which is why
`CalibrateEnergy` leaves that estimate unchanged in the comparison below.

## Comparison of the four calibration methods

`validate_calibrate_methods.py` calibrates the 2018–2022 WECC county
estimate (`loads/wecc/wecc_estimate.csv.gz`) and the WECC240 node load
allocated from it (`loads/wecc/node_estimate_cf.csv`, the 113 nodes that
receive US county load) with each method `CalibrateConfig` can choose,
using `CalibrateTotal` with the unscaled rooftop PV
(`loads/wecc/county_dg.csv.gz`) held fixed:

	python validate_calibrate_methods.py

Each method is fitted to its own data: county EIA-861M monthly energy
(`wecc/county_mwh.csv`) for `CalibrateEnergy`; state monthly energy and
CAISO/WECC monthly peaks (`_test/data/energy_target.csv`,
`peak_target.csv`, `state_groups.csv`) for `CalibrateEnergyPeak`, with a
reduced 8-candidate weight search; each US WECC BA's monthly EIA-930
maximum and minimum (`_test/data/ba_minmax_target.csv`), calibrating the
BA's share of the units, for `CalibratePeaks`; and each BA's hourly
EIA-930 demand for `CalibrateHourly` (`missing="keep"`). Node memberships
(state, CAISO, BA) are the county memberships weighted by net energy.

Every result is compared with the uncalibrated estimate (hourly gross load
of every unit, pooled; MAPE over hours with positive load), with the state
energy targets (monthly net energy, 60 months × 13 states) and with the
peak targets (monthly CAISO and WECC net peaks, 60 months × 2 regions).
MAPE, MAE, RMSE and R² are over the pooled observations, with the
reference as $y$.

**WECC counties (407)**

| Method | Fitted to | Est. MAPE (%) | Est. MAE (MW) | Est. RMSE (MW) | Est. R² | Energy MAPE (%) | Energy MAE (GWh) | Energy RMSE (GWh) | Energy R² | Peak MAPE (%) | Peak MAE (MW) | Peak RMSE (MW) | Peak R² |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Estimate (uncalibrated) | — | 0.0 | 0 | 0 | 1.000 | 17.4 | 891 | 1,906 | 0.872 | 18.3 | 8,065 | 9,111 | 0.945 |
| `CalibrateEnergy` | unit energy | 0.000 | 0.0 | 0.0 | 1.000 | 17.4 | 891 | 1,906 | 0.872 | 18.3 | 8,065 | 9,111 | 0.945 |
| `CalibrateEnergyPeak` | state energy, regional peaks | 72.8 | 52 | 128 | 0.962 | 0.004 | 0.7 | 2.2 | 1.000 | 0.000 | 0.0 | 0.0 | 1.000 |
| `CalibratePeaks` | BA monthly max/min | 20.8 | 36 | 120 | 0.967 | 11.9 | 395 | 737 | 0.981 | 2.3 | 1,470 | 1,916 | 0.998 |
| `CalibrateHourly` | BA hourly demand | 23.6 | 40 | 147 | 0.951 | 12.5 | 412 | 717 | 0.982 | 1.7 | 721 | 925 | 0.999 |

**WECC240 nodes (113)**

| Method | Fitted to | Est. MAPE (%) | Est. MAE (MW) | Est. RMSE (MW) | Est. R² | Energy MAPE (%) | Energy MAE (GWh) | Energy RMSE (GWh) | Energy R² | Peak MAPE (%) | Peak MAE (MW) | Peak RMSE (MW) | Peak R² |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Estimate (uncalibrated) | — | 0.0 | 0 | 0 | 1.000 | 17.1 | 891 | 1,905 | 0.872 | 18.5 | 8,150 | 9,221 | 0.943 |
| `CalibrateEnergy` | unit energy | 0.000 | 0.0 | 0.0 | 1.000 | 17.1 | 891 | 1,905 | 0.872 | 18.5 | 8,150 | 9,221 | 0.943 |
| `CalibrateEnergyPeak` | state energy, regional peaks | 49.9 | 193 | 298 | 0.910 | 0.009 | 0.7 | 2.4 | 1.000 | 0.000 | 0.0 | 0.0 | 1.000 |
| `CalibratePeaks` | BA monthly max/min | 18.9 | 127 | 228 | 0.947 | 11.9 | 392 | 734 | 0.981 | 2.5 | 1,578 | 2,000 | 0.997 |
| `CalibrateHourly` | BA hourly demand | 20.5 | 142 | 267 | 0.928 | 12.6 | 409 | 717 | 0.982 | 1.8 | 803 | 1,003 | 0.999 |

- **`CalibrateEnergy` changes nothing.** The estimate is already scaled so
  each county's monthly net energy equals its EIA-861M allocation (DESIGN
  decision 15; largest difference 0.0015%), so the method is an identity
  on both panels.
- **The two energy references disagree.** The county allocations in
  `county_mwh.csv` sum to about 326 TWh/y for California and 8.6 TWh/y for
  Wyoming, while `energy_target.csv` has about 250 and 16 TWh/y. The
  estimate's 17% state energy MAPE is this difference, not hourly shape.
- **`CalibrateEnergyPeak` meets its targets by distorting the shape.** It
  matches state energy (0.004% MAPE) and attains the CAISO and WECC
  ceilings exactly, but to move California down and Wyoming and Nevada up
  by 20–90% it changes the median county by 66% (MAPE vs the estimate;
  Esmeralda, Lincoln, Lander and Nye NV reach the 200% relative-RMS cap),
  and the nodes by 50%. On nodes, May 2018 and June 2019 fell back from
  the selection tolerances (logged) but still met the targets.
- **`CalibratePeaks` and `CalibrateHourly` are close to each other.** Both
  change the estimate by about 20% (MAPE) with R² 0.93–0.97, bring the state
  energy error from 17% to 12% and the regional peak error from 18% to
  about 2% without being fitted to either; `CalibrateHourly` is closer on
  peaks, `CalibratePeaks` closer to the estimate's shape. Their remaining
  energy error is again mostly the state energy reference (EIA-930 demand
  includes losses and is assigned to states through BA factors).
- Node statistics differ from county ones mostly through aggregation:
  errors in MW are larger per unit (fewer, larger units) and relative
  errors smaller.

## Comparison to existing models

| Method | Spatial unit | Test design | MAPE (%) |
| ------ | ------------ | ----------- | -------- |
| Linear regression benchmark [1,2] | System; zones | Next year, actual weather | 5.22; 7.00 [a] |
| Regression with recency effect [2] | System; zones | Next year, actual weather | 4.27; 6.13 [a] |
| Operator adequacy method [3] | National | Next year, actual weather | 4.8 |
| Dense neural network [3] | National | Next year, actual weather | 2.8 |
| Per-area perceptron meta-model [4, 5] | 54 balancing areas | Next year, simulated weather | < 5 for 9 of 10 largest |
| TSGAM | County (6 WECC medoids) | Same-year holdout, actual weather | 0.55–2.05 [b] |

Notes:
- [a] System level; mean over zones. 
- [b] Best per county; 98% of all 6480 fits are below 3%, maximum 3.76%.

## References

1. T. Hong, P. Pinson, and S. Fan, “Global energy forecasting competition 2012,” Int. J. Forecasting, vol. 30, no. 2, pp. 357–363, 2014.

2. P. Wang, B. Liu, and T. Hong, “Electric load forecasting with recency effect: A big data approach,” Int. J. Forecasting, vol. 32, no. 3, pp. 585–597, 2016.

3. C. Behm, L. Nolting, and A. Praktiknjo, “How to model European electricity load profiles using artificial neural networks,” Applied Energy,
vol. 277, p. 115564, 2020.

4. C. R. McGrath, C. D. Burleyson, Z. Khan, A. Rahman, T. Thurber, C. R. Vernon et al., “tell: A Python package to model future total electricity loads in the United States,” J. Open Source Softw., vol. 7, no. 79, p. 4472, 2022.

5. Pacific Northwest National Laboratory, “TELL user guide: Model evaluation,” [Online]. Available: https://immm-sfa.github.io/tell/user_guide.html, accessed Oct. 9, 2026.