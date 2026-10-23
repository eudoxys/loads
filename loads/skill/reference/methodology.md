# Methodology

How `loads` produces a county load, what it promises, and what it does
not. Use this to explain results and to decide whether `loads` fits the
question. Summarized from the `loads` package docstring and source
(https://www.eudoxys.com/loads).

## Pipeline

```
ResStock 2018 (5 types) ─┐ × Census housing units ─────────► Residential
ComStock 2018 (14 types) ┘ × OpenEI floor area (no apts) ──► Commercial
NLR #97 county inventories, annual → average MW, flat ───────► Industry, Agriculture
transportation ──────────────────────────────────────────────► 0
                      Σ sectors (2018)  +  NSRDB 2018 weather  →  TSGAM fit
                      NSRDB weather for the target period      →  predict / sample
county panel + state energy + regional peaks + DG  →  Calibrate (optional, per UTC month)
```

1. **Building-stock end uses.** NLR (formerly NREL) ResStock and ComStock
   2018 AMY end-use load profiles per county and building type (OEDI S3).
   End uses are collected into `baseload`, `cooling`, `heating` and DG
   (`Residential.COLLECT`, `Commercial.COLLECT`).
2. **Scaling.** Residential types are weighted by their stock unit counts
   and rescaled to Census housing units (the 2020s estimates; `Units`
   falls back to their earliest year for 2018). Commercial is rescaled from
   stock floor area to OpenEI floor area, excluding apartments (counted in
   residential) and unmatched floor area.
3. **Industry and agriculture.** Annual county energy from NLR submission
   #97 (TBtu/yr → MW average). No hourly, daily or seasonal shape; not
   weather-driven; not checked against EIA.
4. **Training frame.** The 2018 sector loads plus the county's NSRDB 2018
   weather (county centroid) form the training set; total = Σ sectors,
   DG = −(|res DG| + |com DG|), net = total + DG.
5. **TSGAM.** `tsgam_estimator` fits, per target column, a time-series
   generalized additive model: Fourier terms for yearly/weekly/daily
   periodicity, spline responses to lagged weather (temperature and
   humidity for loads; direct and diffuse irradiance for DG), and an AR
   residual model. It is solved as a convex problem (CVXPY, CLARABEL).
6. **Prediction / sampling.** Applying the fitted model to another year's
   weather gives the expected load (`samples=0`); AR sampling gives
   realizations with realistic hour-to-hour variability.
7. **Calibration (a separate step).** `Total` is not adjusted to any
   reported total. `loads.calibrate.Calibrate` shapes a panel of county (or
   node) gross loads with a convex program (Meyers and Chassin's
   hierarchical net-load shaping): per unit and UTC month, a scale and an
   offset so that state net-load energy matches EIA-based targets (soft)
   and regional net-load peaks reach but do not exceed CAISO/WECC
   ceilings from EIA-930 (hard), with DG held fixed. Validated on 2020 WECC
   (see `loads/_validate/README.md`): every state within 0.5% of its energy
   target; CAISO-region net load vs CAISO's reported load −3.7% energy,
   −0.7% peak, 11.2% MAPE.
8. **Precomputed WECC estimate.** `loads/wecc/wecc_estimate.py` predicts
   every WECC county for 2018–2022 with `loads.estimator.Estimator` (using
   the harmonics chosen for the county's cluster medoid) and rescales each
   UTC month to the county's EIA-861M retail sales allocation
   (`county_mwh.csv`, from `Energy` contribution factors) plus its rooftop
   PV (`county_dg.csv.gz`). `node_estimate.py` allocates the *uncalibrated*
   county estimates to WECC240 nodes.

## Promises (from the package)

- the 2018 training frame: one row per hour of 2018 (UTC), the county's 2018
  weather, a sector breakdown whose sum is `elec_total_MW` (DG excluded),
  DG never positive, net = total + DG;
- predictions for another period: the weather inputs and one TSGAM-predicted
  column for every hour (one AR sample, or a percentile of samples, when
  sampling);
- predicted residential/commercial/total load follows temperature and
  humidity, predicted DG follows direct and diffuse irradiance; industrial
  and agricultural load do not depend on weather;
- inputs and training data are cached (`refresh=True` to rebuild);
  predictions are deterministic, samples are not.

## Not promised

- Agreement with EIA or any reported total, for 2018 or any other year,
  unless calibration is applied afterwards (`Calibrate`, or the
  precomputed `wecc_estimate`).
- Industrial/agricultural shape.
- Load growth: predicted years inherit 2018 scaling, so growth only enters
  through what the stock and inventory data encode (commercial floor area
  has no annual growth, issue #8).
- The full sector breakdown in predictions (one column per call).
- Coverage outside years with NSRDB weather; most exercise has been
  2018–2022 in WECC states. Future years need future weather that NSRDB
  does not have.
- Large loads (data centers, NERC "large loads"), EV/transportation load,
  behind-the-meter storage.
- Leading/trailing lag hours when sampling or predicting.

## Interpreting results

- **Expected vs realized.** Predictions are conditional means given
  weather; they are smoother than real load. Peaks from predictions are
  biased low relative to realized peaks. For peak planning use sample
  ensembles.
- **Weather drives differences between years**, not economics. Year-on-year
  changes in predicted load reflect weather plus whatever growth enters
  through scaling inputs.
- **County centroid weather.** Large counties (e.g. San Bernardino) span
  climates; one weather point is used.
- **Accuracy.** `loads/_validate/README.md` has the `Estimator`
  validation and the 2020 calibration validation against CAISO's reported
  load (calibrated: −3.7% energy, −0.7% peak, 11.2% MAPE, R² 0.53;
  uncalibrated TSGAM: +20.7% energy, 21.6% MAPE), and
  `loads/_explore/explore_estimator_clusters.csv` the hold-out error of
  each harmonics choice per cluster medoid. For a specific county, measure
  it: `Estimator(county_st)` hold-out mode or `Total.test(...)`, then
  report RMSE/MAPE on the held-out rows.
- **Calibrated is not validated per county.** `Calibrate` and
  `wecc_estimate` match state and regional totals; individual counties
  inherit the allocation's errors (e.g. how EIA state sales are split
  among counties).
