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
                      Σ sectors (2018)                         →  Total
                      Σ sectors (2018)  +  NSRDB 2018 weather  →  Estimator TSGAM fit
                      NSRDB weather for the target period      →  Estimator predict
EIA-861M small-scale solar × county share × weather shape  →  DG (DG.merge adds it)
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
4. **Sector sum.** `Total` sums the 2018 sector loads: total = Σ sectors,
   and nothing more (no weather, DG or net load).
5. **TSGAM.** `Estimator` sums the configured sectors' 2018 `enduse` and
   fits, on its log, a time-series generalized additive model
   (`tsgam_estimator`): Fourier terms for yearly/weekly/daily periodicity
   and spline responses to lagged county-centroid NSRDB weather
   (temperature and humidity by default); AR off by default. It is solved
   as a convex problem (CVXPY, SCS by default).
6. **Prediction.** Applying the fitted model to another year's weather
   gives the expected load. There is no sampling.
7. **Distributed generation.** `loads.dgen.DG` allocates the state's
   EIA-861M small-scale solar to the county by energy share and shapes it
   hourly; `DG.merge` adds it as `elec_dg_MW ≤ 0` and sets net load.
8. **Calibration (a separate step).** Neither `Total` nor `Estimator` is adjusted to any
   reported total. `loads.calibrate.Calibrate` shapes a panel of county (or
   node) gross loads with a convex program (Meyers and Chassin's
   hierarchical net-load shaping): per unit and UTC month, a scale and an
   offset so that state net-load energy matches EIA-based targets (soft)
   and regional net-load peaks reach but do not exceed CAISO/WECC
   ceilings from EIA-930 (hard), with DG held fixed. Validated on 2020 WECC
   (see `loads/_validate/README.md`): every state within 0.5% of its energy
   target; CAISO-region net load vs CAISO's reported load −3.7% energy,
   −0.7% peak, 11.2% MAPE.
9. **Precomputed WECC estimate.** `loads/wecc/wecc_estimate.py` predicts
   every WECC county for 2018–2022 with `loads.estimator.Estimator` (using
   the harmonics chosen for the county's cluster medoid) and rescales each
   UTC month to the county's EIA-861M retail sales allocation
   (`county_mwh.csv`, from `Energy` contribution factors) plus its rooftop
   PV (`county_dg.csv.gz`). `node_estimate.py` allocates the *uncalibrated*
   county estimates to WECC240 nodes.

## Promises (from the package)

- `Total`: one row per hour of 2018 (UTC), a sector breakdown whose sum is
  `elec_total_MW`, and nothing more;
- `Estimator`: the weather inputs and one TSGAM-estimated column for every
  hour of the requested years;
- estimated load follows temperature and humidity; industrial and
  agricultural load do not depend on weather;
- `DG.merge`: DG never positive, net = total + DG;
- inputs and sector loads are cached (`refresh=True` to rebuild);
  estimates are deterministic.

## Not promised

- Agreement with EIA or any reported total, for 2018 or any other year,
  unless calibration is applied afterwards (`Calibrate`, or the
  precomputed `wecc_estimate`).
- Industrial/agricultural shape.
- Load growth: predicted years inherit the 2018 stock scaling. `Units` and
  `Floorarea` can extrapolate growth (#19), but the sector models don't
  use it, so it must be applied separately.
- The full sector breakdown in estimates (one column per call).
- Coverage outside years with NSRDB weather; most exercise has been
  2018–2022 in WECC states. Future years need future weather that NSRDB
  does not have.
- Large loads (data centers, NERC "large loads"), EV/transportation load,
  behind-the-meter storage.
- The first lag hours of an estimate.

## Interpreting results

- **Expected vs realized.** Predictions are conditional means given
  weather; they are smoother than real load. Peaks from predictions are
  biased low relative to realized peaks; there is no sampling to correct
  for that. Say so when peaks feed planning decisions.
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
  it: `Estimator(county_st)` hold-out mode (folds with
  `EstimatorConfig(fold=True)`), then
  report RMSE/MAPE on the held-out rows.
- **Calibrated is not validated per county.** `Calibrate` and
  `wecc_estimate` match state and regional totals; individual counties
  inherit the allocation's errors (e.g. how EIA state sales are split
  among counties).
