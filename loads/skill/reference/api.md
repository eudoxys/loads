# `loads` API, verified

Signatures below are copied from the `loads` source in this repository and
checked by `loads/_test/test_skill_loads_api.py`. "Fetches" lists the
first-call downloads (cached afterwards). "Returns" is what the constructed
frame contains. Read [footguns.md](footguns.md) for the traps each entry
mentions.

Public exports (`from loads import ...`): `Aggregator`, `Agriculture`,
`Calibrate`, `COMstock`, `Cluster`, `Commercial`, `DG`, `Energy`,
`Estimator`, `Floorarea`, `Industry`, `Normalize`, `RESstock`,
`Residential`, `Total`, `Transportation`, `Units`, `main` (CLI). `aggregate()` lives in
`loads.aggregate` (`loads.aggregate` is the module, not the function);
`CalibrationError` in `loads.calibrate`; `EstimatorConfig` and
`EstimatorError` in `loads.estimator`. `import loads` does not import
`loads.skill`.

## Total

```python
Total(state: str, county: str, *, Y="elec_total_MW", X=None, dg: bool = False,
      date_range: pd.DatetimeIndex = None, samples: int = None,
      percentile: float = 96, holdout=None, refresh: bool = False)
```

The core model: sector sum for 2018 plus a TSGAM (time-series generalized
additive model, `tsgam_estimator`) fitted per `(state, county, X, Y)` and
used to predict or sample other periods from weather.

- `samples=None` → the 2018 training frame (all sectors, DG, total, net,
  weather). `date_range`, `X`, `percentile` are ignored. `Y` only selects
  `elec` vs `nonelec`.
- `samples=0` → deterministic prediction of `Y` over `date_range`.
- `samples=1` → one autoregressive sample.
- `samples>1, percentile=p` → per-hour p-th percentile across samples,
  returned in column `Y`.
- `samples>1, percentile=None` → `sample_0 … sample_{n-1}` columns.
- `date_range` must be a `pd.DatetimeIndex` (asserted) whenever `samples`
  is not `None`. Weather is fetched for every calendar year it touches.
- `X` defaults to `Total.EXOGENOUS_VARIABLES[Y]`:
  temperature + humidity for residential/commercial/total (elec and
  nonelec), direct + diffuse irradiance for `elec_dg_MW`. Any other `Y`
  needs `X`.
- `dg=True` (#43) merges `loads.dgen.DG` (EIA-861M small-scale solar,
  see [DG](#dg)) with `DG.merge`: `elec_dg_MW` is added, or replaces the
  building-stock PV in the training frame and the predicted DG when
  `Y="elec_dg_MW"`, and `elec_net_MW = elec_total_MW + elec_dg_MW` is set
  whenever `elec_total_MW` is present. So `samples=0, dg=True` returns
  `X`, `elec_total_MW`, `elec_dg_MW`, `elec_net_MW`; the net inherits the
  NaN lag-window edges of the total. `dg=True` raises `ValueError` for a
  `nonelec_` `Y` and for a predicted `Y="elec_net_MW"`. The profile and
  EIA file come from the class attributes `DG_PROFILE` (`"weather"`) and
  `DG_SOURCE` (`None` = download). CLI: `loads print ... -G`.
- `holdout` is accepted and unused (use `Total.test`).
- Not calibrated to EIA or any reported total, in any year.
- Output index is converted to UTC and named `timestamp`. The first and
  last 3 rows of each predicted column are NaN.

Fetches: NSRDB weather (credentials), ResStock/ComStock (OEDI S3), Census
housing units, OpenEI floor area, NLR #97 industry/agriculture.

Class attributes worth knowing: `TRAINING_YEAR = 2018`, `TSGAM_CONFIG`
(harmonics `[4, 4, 12]` for year/week/day, 7-knot splines, lags −3…+3,
AR lags 1–9, CLARABEL), `TRANSFORMATIONS` (DG fitted as −DG), `cache`
(in-memory fitted estimators; set `Total.cache = None` to disable),
`CACHEDIR`, `INDUSTRY_LOADSHAPE`/`AGRICULTURE_LOADSHAPE` (None = flat).

Class methods:

- `Total.test(state, county, holdout, X=["temperature_degF"],
  Y="elec_total_MW", n_samples=0, refresh=False)` — fits on 2018 minus
  `holdout` rows and returns `X`, `Y` (actual), `predict` and optionally
  `sample[_n]`. Use for skill scores.
- `Total._clear_cache()` — drop fitted estimators (private but used by
  upstream sweeps).
- `Total.makeargs(**kw)` — keeps only kwargs annotated in `__init__`
  (CLI plumbing; drops `year`).

## Residential / Commercial

```python
Residential(state: str, county: str, *, collect=None, refresh=False)
Commercial(state: str, county: str, *, collect=None, refresh=False)
```

2018 hourly sector loads by category (see [data-model.md](data-model.md)).
`Residential` sums the five ResStock building types weighted by stock
units and rescales to Census housing units for `year=2018`, which the
2020-2024 estimates table does not have, so `Units` falls back to its
earliest year and logs a warning. `Commercial` sums the 14
ComStock types and rescales stock floor area to OpenEI floor area,
excluding apartments and unmatched area. `collect` overrides the end-use →
category map (`COLLECT`). There is no year argument.

## RESstock / COMstock

```python
RESstock(state: str, county: str = None, building_type: list[str] = None, refresh=False)
COMstock(state: str, county: str = None, building_type: list[str] = None, refresh=False)
```

Raw end-use data per building type: W per housing unit (`units` column) or
W/sf (`floor_area` column). Use for end-use studies (e.g. electrifying
heating: compare `gas_heating` and `elec_heating`).

## Industry / Agriculture

```python
Industry(state=None, county=None, loadshape=None, refresh=False)
Agriculture(state=None, county=None, loadshape=None, refresh=False)
```

Annual county energy from NLR submission #97 converted to average MW.

- No arguments → all counties (MultiIndex `state, county`); state only →
  that state's counties; state + county without `loadshape` → a one-column
  frame indexed by column name (`Industry("CA","Alameda").loc["elec_total_MW"]`).
- `loadshape` as a one-column DataFrame (column `0`, date/time index) or a
  dict (`shape`, `start`, `end`, `freq`) → hourly frame = shape × average
  MW. The shape must **average** 1.0 to preserve annual energy (a vector of
  ones gives the flat load). It is ignored unless both `state` and `county`
  are given.
- Unmatched NREL FIPS codes are folded into the previous county; a county
  absent from the NREL data has zero load (since `608b9c4`; before that it
  got the previous county's load, so rebuild older caches with
  `refresh=True`).
- Also carries always-zero `elec_cooling_MW`, `elec_heating_MW`,
  `elec_dg_MW`, `nonelec_cooling_MW`, `nonelec_heating_MW` columns.

## Units / Floorarea

```python
Units(state: str, county: str = None, year: int = None, refresh=False, aggregate=sum,
      backcast: bool = False)  # -> float
Floorarea(state=None, county=None, year=None, refresh=False)
```

Census housing units (2020–2024 estimates) and OpenEI commercial floor area
(2019) by building type. Scaling inputs for the sector models.

Load growth (#19): `Units` extrapolates years after 2024 at
`Units.GROWTH_RATE` (1%/yr) and, with `backcast=True`, years before 2020
(otherwise it uses 2020 and logs a warning). `Floorarea` scales its 2019
data to any other `year` at `Floorarea.GROWTH_RATE` (1.75%/yr), forward or
back. Both rates are class attributes; set them before constructing. The
sector models do **not** use the growth: `Residential` asks for
`Units(year=2018)` without `backcast` (so 2020 units) and `Commercial` for
the 2019 floor area, so `Total` predictions for any year carry no growth.
Apply growth yourself (e.g. scale a predicted residential series by
`Units(st, co, 2030) / Units(st, co, 2020)`) and say so.

## Estimator

```python
Estimator(county_st: str, years: list[int] = None, *, config: EstimatorConfig = None)
EstimatorConfig(verbose=False, debug=False, log=True, ar=False,
                solver="CLARABEL", harmonics=[4, 4, 6],
                sectors=["residential","commercial","industrial","agricultural"],
                enduse="elec_total_MW", weather=["temperature_degF","humidity_pc"],
                keep_actuals=True, holdout="5d", fold=0)
```

`outlier_regularizer` (1e-4) and `outlier_threshold` (5.0) are class
attributes of `EstimatorConfig`, not fields: they cannot be passed to the
constructor, and the threshold is not applied to the training data.

Newer TSGAM front end, one string location (`"Alameda CA"`).

- `years=None` → hold-out test on 2018: columns weather, `actual`,
  `prediction`, `status` (`T` train / `H` held out). `holdout` is `"<N>h|d|w|m"`
  (every N-th hour/day/week/month) or a callable `frame -> index`.
- Folds (#38): a `"<N>…"` holdout splits the intervals into N groups,
  `(ndx + 1) % N`, and `fold` picks the withheld group. `fold=0` (default)
  is the old every-Nth-interval holdout; `0 < k < N` shifts it by k;
  `fold=True` fits N models, so `prediction` holds each row's
  **out-of-fold** prediction, every valid row has `status == "H"`, a `fold`
  column says which fit withheld it, and `attrs["folds"]` holds per-fold
  `MAE`, `RMSE`, `MAPE` (%) and their `mean` row. Costs N fits. A nonzero
  `fold` with a callable `holdout` raises `EstimatorError`. `attrs` are
  dropped by most pandas operations: read `attrs["folds"]` right away.
- `years=[...]` → weather + `enduse` for those years, predicting every year
  from min to max then dropping the unrequested ones. 2018 rows are the
  actual training data when `keep_actuals`.
- Fits in log space by default (`log=True`), so it cannot represent zero
  or negative loads (no DG/net). AR off by default.
- Years without NSRDB weather raise `EstimatorError`.
- The first hours of each prediction are NaN (exogenous lags).
- `sectors=["residential"]` skips the national commercial, industrial and
  agricultural downloads (what the package's own tests do).

`Total` and `Estimator` use different TSGAM configurations and give
different predictions. Use one per study and say which.
`loads/wecc/wecc_estimate.csv.gz` is built from `Estimator` with per-medoid
harmonics (see [workflows.md](workflows.md)).

## Normalize

```python
Normalize(source: str | pd.DataFrame, *, timestamps: dict, timezone: str = None,
          scales: dict[str, float] = None, mapping: dict[str, str] = None,
          groups: dict = None, weather: str = None)
Normalize.STANDARD_COLUMNS   # elec_{baseload,heating,cooling,dg,total,net}_MW,
                             # nonelec_{baseload,heating,total}_MW
```

Imports measured or third-party load data (AMI, SCADA, a utility CSV) as an
hourly `loads`-style frame (#36), for comparison with or calibration of
model output.

- `source`: a DataFrame, or a CSV path or URL.
- `timestamps` (required): exactly one source column mapped to
  `pd.DatetimeIndex` (the primary time) plus columns mapped to callables
  returning a `TimedeltaIndex` that are added to it (e.g. hour-ending →
  hour-beginning, a UTC offset column). Naive times are localized to
  `timezone` (default `"UTC"`, an IANA name otherwise; DST handled by
  `DST_STRATEGY`); the result is converted to UTC.
- `mapping` (required): standard column → source column, one to one.
  `scales`: source column → factor (e.g. `1e-3` for kW → MW).
- `groups`: source column → grouping column(s); the result gets a
  MultiIndex `(group..., timestamp)`. Select one group (`.xs(...)`) to get
  a plain hourly frame.
- `weather="County ST"` merges `weather.Weather` columns (NSRDB
  credentials).
- Aggregation: rows are averaged (`mean()`) within each hour **and across
  all rows sharing that hour**. So without `groups` the result is the
  *average* source unit (e.g. average meter), not their sum **[tested]**,
  and sub-hourly *energy* readings (kWh per 15 min) come out as the
  per-interval mean, not hourly energy, so scale them by intervals per hour
  **[tested]**. Power readings (kW) need no such factor. Super-hourly data
  is not upsampled.
- The module docstring's example call is ungrouped, but its output
  (about 21.7 MW) is the *meter-summed* total; the call as written returns
  the average meter (0.0215 MW) for `loads/_test/ami.csv.gz`.

## Calibrate

```python
Calibrate(load: pd.DataFrame, *, energy, peak, dg=None, states=None, regions=None,
          energy_weight=100.0, drive=None, shape_weight=1.0, ridge=1e-8,
          peak_multiple=5.0, relative_rmse=2.0, search=False, verbose=False,
          progress=None)
```

Convex net-load shaping (second-order-cone program, CVXPY + CLARABEL) of a
panel of units (counties or nodes) to published regional totals.

- `load`: hourly **gross** load `X` (MW), one column per unit, no NaN, no
  negative values (`CalibrationError` otherwise). With `states=None` each
  column must be `"County ST"`: the state is the last word.
- `dg`: DG **output** `D` (MW, ≥ 0) with the same columns. Passing
  `elec_dg_MW` (≤ 0) raises `CalibrationError`; negate it first.
- `energy`: **net-load** (`L − D`) energy targets in MWh per state;
  `peak`: net-load peak ceilings in MW per region. Each may be a dict or
  Series (same targets for every month) or a DataFrame indexed by UTC month
  start (one row per month). Both are required, keyword-only, and `peak`
  needs at least one region: `peak={}` raises `KeyError` while building
  the region table. A state with load but no target raises.
- `regions`: unit × region membership in [0, 1] (or dict of region → unit
  list); default makes every unit a full member of every region.
- Each **UTC calendar month** is solved independently with its own targets,
  choosing per unit a scale `s ≥ 0` and offset `b` so `L = s·X + b`: an
  affine shaping, not a proportional rescale. Expect small steps at month
  boundaries. Identically zero units are left unchanged.
- `search=True` solves the predeclared grid (`ENERGY_WEIGHTS` × `DRIVE_SCALES`; 88
  candidates for two regions, 32 for one) per month and picks the
  least-distorting candidate within `PEAK_SHORTFALL_TOL` (1e-4),
  `STATE_ENERGY_TOL` (0.5%) and nonnegativity, else falls back (logged as
  a warning, `summary.selection` says so). `search=False` uses
  `energy_weight`/`drive` as given. `progress(done, total, info)` reports
  each solve.
- Hard unit safeguards (`peak_multiple`, `relative_rmse`) can make the
  program infeasible → `CalibrationError`.

Returns the shaped gross load `L` (same index/columns) with attributes
`net` (`L − D`), `parameters` (scale, offset, per block and unit),
`states` (target, input and shaped energy and errors), `regions` (target,
input and shaped peak, peak times, duals), `summary` (per block: selection,
weights, fit metrics), `constraints` (dual summaries) and `sweep` (every
candidate when searching). Derived frames are plain DataFrames, so the
attributes are lost after arithmetic.

WECC 2018–2022 targets used by the package's own test and validation are in
`loads/_test/data/` (`energy_target.csv`, `peak_target.csv`,
`state_groups.csv` with fractional CAISO membership; see its README) and
the EIA-scaled DG in `loads/wecc/county_dg_scaled.csv.gz`.

`loads.skill.shape_to_targets` wraps it (DG sign conversion, input checks,
provenance). For a proportional match to one county's energy use
`scale_to_energy`/`scale_monthly`; for an affine energy + peak fit of one
series, `fit_energy_peak`. The pre-rewrite API (`fit_load`, `integrate`,
`Calibrate.load`, `Calibrate.solar`, `start`/`end`/`scale`/`offset`) no
longer exists.

## Energy

```python
Energy(state: str, counties: str | list[str] | None, year: int | tuple | list,
       month: int = None, *, groupby="1MS", datetime_format=None,
       progress=None, refresh=False)
```

Periodic MWh per county (`"County ST"` columns) from
`Total(..., samples=0)` predictions of `elec_total_MW`. Pass `year` as a
2-item list/tuple (`[2018, 2022]`); a bare int fails at `min(year)` when
building the cache name. The cache name does not include the county list:
calling it twice for different counties in the same state and period
returns the first result unless `refresh=True`. A county whose `Total`
fails is omitted with a warning (its column is absent, not zero);
`RuntimeError` if every county fails.

## DG

```python
DG(state: str, county: str, date_range: pd.DatetimeIndex = None, profile="weather",
   source: str = None, refresh=False)
DG.merge(data, state, county, **kwargs)        # add DG to a frame, recompute net
SmallScaleSolar(year, state=None, source=None, refresh=False)
compile(years=(2018, 2022), target="county_dg_eia.csv.gz", profile="weather", system="WECC")
```

Hourly county rooftop PV (#43), following the REGROW EIA-861M procedure:
for each UTC month, the state's EIA-861M small-scale solar generation
(all sectors) times the county's share of the state's energy use
(`loads/wecc/county_mwh.csv`), spread over the hours by a profile, so
monthly county DG energy matches EIA. Returns one column `elec_dg_MW`,
**≤ 0** (negative load), indexed by UTC `timestamp`.

- `date_range` defaults to 2018; naive times are taken as UTC.
- `profile="weather"`: NSRDB global horizontal irradiance (needs NSRDB
  credentials; ignores panel orientation and temperature). `"dgen"`: the
  bundled `county_dg.csv.gz` dGen shape, 2018–2022 only; counties missing
  or all zero there use their state's total dGen shape.
- `source`: a local EIA-861M file ("Monthly Totals- States" layout);
  `None` downloads with `eia.Form861m`. Hours of months EIA has not
  published are NaN (and not cached).
- Needs `loads/wecc/county_mwh.csv`, which a non-editable install does
  not ship (`FileNotFoundError`); use a clone with `pip install -e .`.
- Shares exist only for counties in `county_mwh.csv`, i.e. every county of
  the 13 WECC states, 2018–2022; other years use the same month of the
  nearest year. Any other county gets **zero DG with a `UserWarning`**
  **[tested]**.
- Months are UTC; EIA's are local (less than 1% energy shift).
- `compile` (`python3 -m loads.dgen --target=...`) writes every WECC
  county as **positive** output, the convention `Calibrate(dg=...)`
  expects.

This replaces the earlier `DG(..., source="wecc/county_dg.csv.gz")` file
reader. The bundled `county_dg.csv.gz`/`county_dg_scaled.csv.gz` files
still hold positive dGen output; `loads.skill.wecc_dg` reads them in the
`loads` convention.

## Aggregator / aggregate

```python
Aggregator(targets: list[str], start, end)          # zero panel, .add(target, frame)
aggregate(targets: dict[str, (lat, lon)], dt_range: int | list[int] | DatetimeIndex,
          column: str, refresh=False) -> (DataFrame, mapping)
```

`aggregate` maps every **WECC** county to its nearest target and sums
`Total(..., samples=1)` — a random AR sample, not a prediction — then caches
by year and column only (changing targets needs `refresh=True`). A list of
years is not handled correctly. `Aggregator.add(target, frame)` takes a
frame with a column named `target`. Prefer `loads.skill.nearest_nodes` +
`allocate` on frames you produced in a known mode, or the precomputed
`node_estimate` for WECC240.

## Cluster

```python
Cluster(counties: list[str], column: str, threshold=0.99, preprocess=None,
        progress=None, refresh=False)
cluster.kmeans(n_clusters: int)  # sets .medoids, .members, .closest, .centroids
```

SVD + energy-weighted k-means of county load shapes (rolled to local
standard time). `loads/clusters.csv` maps each WECC county to one of six
`elec_total_MW` medoids (Lincoln OR, Maricopa AZ, Multnomah OR, San Luis
Obispo CA, Solano CA, Spokane WA), and
`loads/_explore/explore_estimator_clusters.csv` holds the hold-out error of
each `Estimator` harmonics choice per medoid (used by
`wecc/wecc_estimate.py`). The `configs.csv` of `Total` settings that some
docs still mention was removed with the deprecated modules (#39).

## CLI

```
loads {print,plot} [-S STATE] [-C COUNTY] [-D DATASET] [-B BUILDING_TYPE]
      [-Y YEAR] [-o OUTPUT] [-f FORMAT] [-p PRECISION] [-w] [-d]
```

Commands: `print`, `plot` (`viewer`, `test`, `help`, `info` are accepted
but not functional). `-D total` (default) prints **2018 training data**:
`-Y` only reaches the `weather` dataset. `plot` draws only `weather` and
`total`. Use `python3 -m loads.skill county|series` for year-aware output.
