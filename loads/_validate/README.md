Validation
----------

## Estimator

The `validate_estimator_marimo.py` notebook validates the choice of holdout
and harmonics of `loads.estimator.Estimator` on individual counties. Run the
marimo notebook

	marimo run validate_estimator_marimo.py

## Calibration

The `validate_calibrate_marimo.py` notebook compares the CAISO-region net
load of the calibrated 2020 WECC county loads with the hourly load CAISO
reported for 2020 (`loads/caiso/2020.csv`). The calibration uses the default
settings of `loads/_explore/explore_calibrate_marimo.py`, i.e., the
predeclared weight search and selection rule of `loads.calibrate.Calibrate`
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
| Rooftop PV (DG) $D$ | `loads/wecc/county_dg_scaled.csv.gz` | county rooftop PV output (MW, positive), scaled to EIA small-scale solar generation (see below) |
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

**Rooftop PV.** `loads/wecc/county_dg.csv` has about a third of EIA's
estimated California small-scale solar generation, no year-to-year growth,
and no DG for 39 WECC counties (e.g., Kern, San Bernardino, Ada, Canyon,
Bernalillo, Clackamas). `loads/wecc/county_dg_scale.py` builds
`county_dg_scaled.csv.gz` from it:

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
   `county_dg_scaled.csv.gz` with $X$.
3. **Calibration.** `validate_calibrate.calibrated_load()` runs
   `Calibrate(X,dg=D,energy=...,peak=...,regions=...,search=True)`. For each
   UTC month it finds a per-county scale and offset of the gross load so
   that the shaped net load $L-D$ meets each state's energy target and
   reaches, without exceeding, the CAISO and WECC peak targets, where the
   regional net load is $\sum_j g_j(L_{tj}-D_{tj})$ with $g_j$ the county's
   membership. It searches the predeclared 88-point weight grid and applies
   the selection rule. Results are cached as `calibrate_L_2020.csv.gz`,
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
the EIA-scaled DG (CAISO-region DG 15.5 TWh, peak 7.5 GW) and, for
reference, the unscaled `county_dg.csv` DG (4.4 TWh, 2.1 GW):

| Model | Energy error | Peak error | MAPE | CV(RMSE) | R² | Correlation |
| ----- | ------------ | ---------- | ---- | -------- | -- | ----------- |
| TSGAM input, unscaled DG | +25.7% | +21.7% | 26.7% | 31.5% | −1.44 | 0.775 |
| Calibrated, unscaled DG | −3.8% | −0.7% | 14.5% | 17.1% | 0.28 | 0.771 |
| TSGAM input, scaled DG | +20.7% | +15.3% | 21.6% | 24.4% | −0.47 | 0.854 |
| **Calibrated, scaled DG** | **−3.7%** | **−0.7%** | **11.2%** | **13.9%** | **0.53** | **0.844** |

The scaled DG reproduces the reported midday dip; the calibrated net load is
within about 1.6 GW of the reported load between 10:00 and 16:00 Pacific in
April and August. The largest remaining errors are at night, when the
calibrated load is about 2–5 GW (April) and 8–10 GW (August) below the
reported load between midnight and 04:00 Pacific,
and in February, August and November, whose energy is 11–14% low. The peak
error is the difference between the EIA-930 CAISO peak target and the peak in
`loads/caiso/2020.csv`.

### Known gaps

- **Losses.** Peak targets and the CAISO reference include transmission and
  distribution losses. The state energy targets are not adjusted for losses,
  so the calibrated regional energy may fall short of the reported energy by
  about the loss rate (EIA estimates about 5% nationally).
- **DG shape.** Only DG energy is scaled to EIA. Errors in its hourly shape or
  county distribution appear directly as net-load errors in daylight hours.
- **Membership.** Shares are annual and based on 2020; partly non-CAISO
  counties listed above remain full members.

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