# eudoxys/loads — package design (draft 1)

Status: draft, 2026-10-22. Reconstructed from the code on `main` at
`608b9c4` to record the design for version 1; the decisions below describe
what is implemented and need the maintainer's confirmation. Issue and PR
numbers (`#n`) refer to `github.com/eudoxys/loads`.

## Purpose

`loads` estimates hourly electricity demand (MW) for each US county, broken
down by economic sector, for a requested period, driven by that county's
actual weather. It is meant for power-system planning studies that need a
realistic county or network-node load shape for a specific year.

- **Provides:** 2018 reference-year sector loads (residential, commercial,
  industrial, agricultural) and their end-use split; TSGAM predictions and
  samples of a load column for other periods; county rooftop-PV distributed
  generation (DG) and net load; calibration of a panel of county loads to
  state energy and regional peak targets; aggregation of counties onto
  network nodes (WECC240).
- **Excluded:** transportation load (stub, reported as zero); wind DG;
  utility-scale generation; load growth and electrification scenarios
  (planned, #19); weather data (lives in `eudoxys/weather`); EIA form access
  (lives in `eudoxys/eia`); the WECC240 network model (lives in
  `eudoxys/wecc240`).
- **Coverage:** the accessors work for any US county with ResStock/ComStock
  data; the TSGAM, calibration, DG and node work has been exercised for the
  407 US WECC counties in 2018–2022.

## Decisions settled

Numbers are permanent: add `Nb` rows for related later decisions; edit a
reversed decision in place and note the date.

| # | Decision |
|---|---|
| 1 | The county is the modeling unit. Network nodes are built by aggregating counties (`loads.aggregate`, `wecc/node_estimate.py`), never modeled directly. |
| 2 | 2018 is the reference (training) year, because ResStock/ComStock 2018 AMY is the hourly source. Industrial and agricultural inventories are 2019 annual energy. `Total.TRAINING_YEAR = 2018`. |
| 3 | Residential load is ResStock building-type shapes scaled by Census housing units; commercial load is ComStock building-type shapes scaled by OpenEI floor area. |
| 4 | Industrial and agricultural load are spread evenly over the year (flat shape) unless a `loadshape` is supplied. They do not respond to weather. |
| 5 | Other periods are predicted with a TSGAM (`tsgam_estimator`) fitted to the 2018 load and the county's NSRDB weather (`temperature_degF`, `humidity_pc`; `direct_Wpms`, `diffuse_Wpms` for `elec_dg_MW`), on log load. |
| 6 | Every data accessor subclasses `pd.DataFrame` and does its work in `__init__`; `Units` subclasses `float`. |
| 7 | Every expensive accessor is cache-first through `eudoxys/cache`, namespaced `package="loads"` with a cache `version` that is bumped when the cached format changes; `CACHEDIR` class attribute and `refresh` argument. |
| 8 | Columns encode fuel, category and unit: `{elec\|nonelec}_{baseload\|cooling\|heating\|total\|dg\|net}_MW`; `Total` reports `elec_{sector}_MW`. Weather columns keep `weather.Weather` names. |
| 9 | Time index is hourly, tz-aware UTC, named `timestamp`, hour-beginning. |
| 10 | DG is a negative load in `elec_dg_MW`; `elec_net_MW = elec_total_MW + elec_dg_MW`. |
| 12 | Calibration solves the Meyers–Chassin hierarchical net-load shaping SOCP: per-unit affine map $L=sX+b$, soft per-state energy targets, hard regional peak ceilings, DG fixed; solved independently per UTC calendar month. |
| 12b | Calibration weights are not tuned per run: with `search=True` a predeclared grid (`Calibrate.GRID`) is solved and a fixed rule selects the result (peak shortfall ≤ `PEAK_SHORTFALL_TOL`, state energy error ≤ `STATE_ENERGY_TOL`, nonnegative load, then least shape RMSE). |
| 13 | Counties are clustered by SVD + k-means on `elec_total_MW`; k = 6 (`loads/clusters.csv`). A cluster's medoid stands in for its members when per-county tuning is too costly. |
| 14 | Estimator harmonics for each medoid are the most parsimonious within 1% of the best found in the sweep (`_explore/explore_estimator_clusters.csv`); the WECC estimate uses the MAPE row. |
| 15 | The WECC county estimate keeps 2018 actual sector loads and rescales each month of 2018–2022 so its energy equals the EIA 861M retail sales allocated to the county plus the county's DG (gross load). |
| 16 | County → node allocation: counties containing WECC240 load busses split in proportion to bus load; other counties go wholly to the nearest load node; Canadian and Mexican node loads come from `wecc240` node files. Factors are constant in time. |
| 17 | Sibling packages are dependencies through `git+` URLs in `requirements.txt`; dependencies are dynamic in `pyproject.toml`. Python is pinned to 3.12. |
| 18 | Tests have two tiers: fast offline tests always run; networked tests are marked `network`, use Alameda CA or a single month, and are skipped when they would need a full WECC build that is not in the cache. |

## Conventions inherited

From the `eudoxys-package` skill (`github.com/eudoxys/claude`) and sibling
packages:

- `eudoxys/cache`: cache paths, `Cache.CACHEDIR`, `cache backup`.
- `eudoxys/fips`: `States()`/`Counties()` lookups and validation; county
  names without "County"; WECC membership via `Counties(...).loc["WECC"]`.
- `eudoxys/weather`: NSRDB weather columns and credentials in
  `~/.nsrdb/credentials.json`.
- `eudoxys/eia`: `Form861m` (small-scale solar), `HS861m` (retail sales).
- pdoc docstrings with dashed-underline sections; `@private` hides helpers.
- CLI options named as constructor arguments; `makeargs` filters on
  `__init__.__annotations__`.

## Module layout

```
loads/
  __init__.py        package docs (spec, columns, data-flow diagram)
  cli.py             main(): loads {print,plot} -S -C -D -Y -B -f -o -p -w -d
  # raw sources
  resstock.py        RESstock(state,county=None,building_type=None,refresh=False)
  comstock.py        COMstock(state,county=None,building_type=None,refresh=False)
  units.py           Units(state,county=None,year=None,refresh=False,aggregate=sum) -> float
  floorarea.py       Floorarea(state=None,county=None,year=None,refresh=False)
  # sector models
  residential.py     Residential(state,county,*,collect=None,refresh=False)
  commercial.py      Commercial(state,county,*,collect=None,refresh=False)
  industry.py        Industry(state=None,county=None,loadshape=None,refresh=False)
  agriculture.py     Agriculture(state=None,county=None,loadshape=None,refresh=False)
  transportation.py  Transportation() -> NotImplementedError
  dgen.py            DG(state,county,date_range=None,profile="weather",source=None,refresh=False);
                     DG.merge(data,state,county); SmallScaleSolar(year,state=None,source=None); compile()
  _solar_estimator.py SolarEstimator (private, unused by DG default)
  # models
  total.py           Total(state,county,*,Y,X,dg,date_range,samples,percentile,holdout,refresh)
  estimator.py       Estimator(county_st,years=None,*,config=EstimatorConfig())
  energy.py          Energy(state,counties,year,month=None,*,groupby="1MS",...)
  calibrate.py       Calibrate(load,*,energy,peak,dg=None,states=None,regions=None,search=False,...)
  cluster.py         Cluster(counties,column,threshold=0.99,...)
  aggregate.py       Aggregator(targets,start,end); aggregate(targets,dt_range,column)
  clusters.csv       county_st -> medoid
  wecc/              WECC maintenance scripts and their data (see MANIFEST.md)
  caiso/ isone/      reference ISO hourly loads
  _test/ _validate/ _explore/ _review/
  # planned
  normalize.py       import arbitrary load data into a standard frame (#35, PR #36)
  growth            load growth for commercial floor area and beyond (#8, PR #19)
  estimator.py       holdout folds (#24, PR #38)
  transportation.py  transportation load (no issue yet)
```

### Constructors and columns

Location arguments are `state` (two-letter) and `county` (name without
"County") for the accessors and `Total`; `Estimator`, `Cluster`,
`clusters.csv` and the WECC outputs use `"County ST"`. Every cached
accessor takes `refresh:bool=False`.

| class | index | columns |
|---|---|---|
| `RESstock`, `COMstock` | `timestamp` (2018) | `{fuel}_{enduse}` per building type |
| `Residential`, `Commercial` | `timestamp` (2018) | `elec_{baseload,cooling,heating,total}_MW`, `nonelec_{...}_MW` |
| `Industry`, `Agriculture` | `timestamp` (2019 shape) | `elec_`/`nonelec_` `baseload`, `total`, `net` (flat); cooling, heating, DG columns always zero |
| `DG` | `timestamp` | `elec_dg_MW` (≤ 0) |
| `Total` (training) | `timestamp` (2018) | weather, `elec_{residential,commercial,industrial,agricultural,transportation}_MW`, `elec_total_MW`, `elec_dg_MW`, `elec_net_MW` |
| `Total` (predict/sample) | `timestamp` (`date_range`) | `X` weather columns and `Y` |
| `Estimator` | `timestamp` (`years`) | weather, `enduse`; with `years=None` also `status` (`T`/`H`), `actual`, `prediction` |
| `Energy` | period start | one column per county, MWh |
| `Calibrate` | as `load` | shaped load (MW); `.parameters`, `.summary`, `.states`, `.constraints` |

Composition: `Total` sums the sector frames on the 2018 index;
`elec_total_MW` is their sum and excludes DG. Predictions return only `X`
and `Y`, not the sector breakdown.

## Sources

| output | primary source | fallback | anchor/reconciliation |
|---|---|---|---|
| residential shape | NREL ResStock 2018 AMY (OEDI S3), by county | — (zero frame if a building type is absent) | — |
| residential scale | US Census housing units | — | — |
| commercial shape | NREL ComStock 2018 AMY (OEDI S3), by county | — (zero frame if a building type is absent) | — |
| commercial scale | OpenEI #906 floor area | zero load (logged) | — |
| industrial, agricultural | NREL county inventories (#97), 2019 | — | not checked against EIA |
| weather | NSRDB via `eudoxys/weather` | — | — |
| DG (`DG`, `Total(dg=True)`) | EIA-861M small-scale PV by state and month (`eia.Form861m`), allocated by county share of state load (`wecc/county_mwh.csv`), shaped by NSRDB GHI or dGen county profiles | state dGen profile for counties missing or all zero in dGen; NaN for months without EIA data | monthly county DG = EIA × load share |
| DG (calibration) | NREL dGen nodal DG → `wecc/county_dg.csv.gz` | — | scaled to EIA small-scale PV (`county_dg_scale.py`) |
| county monthly energy | EIA 861M retail sales (`HS861m`), allocated by `Energy` | — | state sales |
| regional peaks | EIA-930 BA demand, cleaned (`_test/data`) | — | CAISO, WECC |
| node map | `eudoxys/wecc240` bus GIS and county–node map | nearest load node | WECC240 bus loads |

## Method

1. **Sector loads (2018).** Build each sector frame from its source, scale
   to the county, and sum into `Total`'s training frame with 2018 weather.
2. **Prediction.** Fit TSGAM on the training frame (log `Y`, yearly/weekly/
   daily harmonics, temperature and humidity); predict or sample `Y` for the
   requested `date_range` from that period's weather.
3. **DG and net load.** With `Total(dg=True)`, allocate the state's monthly
   EIA-861M small-scale PV to the county by load share, shape it hourly,
   and add it (negative) to total load; `dg=False` (default) adds none.
4. **Calibration (optional).** For a panel of counties, solve decision 12
   month by month. State energy is soft (reported, not forced); regional
   peaks are hard ceilings.
5. **WECC estimate.** For each WECC county, estimate 2018–2022 with the
   medoid's harmonics and rescale monthly to gross load (decision 15). The
   monthly energy is forced to match; the hourly shape is not adjusted.
6. **Nodes.** Allocate county loads to WECC240 nodes (decision 16) and add
   foreign node loads. Node loads are not calibrated.

## Outputs

### `loads/wecc/wecc_estimate.csv.gz`

Key: `timestamp`. One column per WECC county (`COUNTY ST`), sorted by state
then county; 407 counties; 2018-01-01 to 2022-12-31 hourly.

| column | dtype | notes |
|---|---|---|
| `timestamp` | datetime, UTC | hour beginning |
| `COUNTY ST` | float | calibrated gross load, MW, 4 decimals |

```
timestamp,Apache AZ,Cochise AZ,Coconino AZ,...
2018-01-01 00:00:00+00:00,123.4279,162.813,174.1101,...
2018-01-01 01:00:00+00:00,127.7161,176.4158,176.2965,...
```

### `loads/wecc/node_estimate.csv.gz` and `node_estimate_cf.csv`

Key: `timestamp`; one column per WECC240 node geohash (uncalibrated MW).
Factors: `county_st, node, cf, method` with `method` in `bus`, `nearest`;
each county's `cf` sums to 1.

## Files and formats

- Cache: `{cache dir}/loads/{version}/{state}/{county}/{code}.csv.gz`, codes
  `R`, `C`, `T_elec_1h_training`, building types, `units`, `MWH_*`, `CF_*`.
- Checked-in outputs are `.csv.gz` with hourly UTC rows and `County ST`
  columns. Their sizes (18–82 MB) make the repo large to clone (see open
  questions).

## Dependencies and gaps in sibling packages

| need | status |
|---|---|
| county lookup by name | `fips.Counties` ✔; duplicate names (Baltimore, St. Louis, VA cities) can't be disambiguated (#33) |
| cache outside site-packages | `Cache.CACHEDIR` override ✔ (used by `conftest.py`); default is inside the `cache` install |
| hourly weather | `weather.Weather` ✔ (NSRDB credentials required) |
| EIA retail sales, small-scale solar | `eia.HS861m`, `eia.Form861m` ✔ |
| TSGAM | `tsgam_estimator` (`nimish/estimator`) ✔; not a Eudoxys package |
| WECC240 bus/node data | read from `eudoxys/wecc240` raw URLs or a sibling clone; not a declared dependency |

## Known issues to handle

Tracked in issues or `CLAUDE.md` "Known rough edges"; listed here because
they bear on the version 1 contract.

- **Packaging.** `pyproject.toml` ships `*.py` only, so `clusters.csv`,
  `wecc/*` and `caiso/*` are missing after a non-editable install (CI uses
  `pip install .`). `version = "0.0.0"` hides the package from `epm`, and
  `keywords` lacks `"eudoxys"`.
- **Stale references.** `loads/__init__.py` and `CLAUDE.md` name
  `loads.cast`, `configs.csv`, `evaluate_lag.py` and `tsgam_evaluate.py`,
  which are not in the repo.
- **Public API.** `loads/__init__.py` re-exports nothing; users import from
  submodules.
- **DG sign.** `wecc/county_dg*.csv*` and `Calibrate(dg=...)` use positive
  DG; `elec_dg_MW` is negative (decision 10). Conversions must be explicit.
- **`Total`.** No `year` argument; CLI `-Y` only reaches `weather` (#26);
  non-contiguous `date_range` is bridged and sampling isn't seeded (#32);
  first/last hours of a prediction are NaN.
- **`DG`.** Months are taken in UTC (EIA's are local, well under 1% of
  monthly energy); `profile="weather"` ignores panel orientation and
  temperature; `profile="dgen"` covers 2018–2022 only. The EIA-861M rewrite
  (PR #43) replaces the cwd-relative source and broken `SolarModel` of #30.
- **`Calibrate`.** Issues #27, #28.
- **Commercial scaling.** Under-scaling by an extra building-type share (#3);
  equal weighting of overloaded building types (#1); no floor-area growth (#8).
- **Other reviews.** `aggregate.py` (#15), `units.py` (#14), `floorarea.py`
  (#13), `total.py` (#12), `cluster.py` (#10).
- **CLI.** `viewer`, `test`, `help`, `info` are accepted but not functional;
  `plot` draws nothing for sector datasets (`case "_":`).
- **Data provenance.** `caiso/`, `isone/` and `wecc/` have no README with
  source URL and retrieval date; `isone/` is not used by any code.
- **Assumptions.** Flat industrial/agricultural shapes (override with
  `loadshape`); WECC240 snapshot bus loads for node splits; zero
  transportation load.

## Version 1 release (proposed)

Proposed scope, for the maintainer to confirm:

1. Packaging: ship curated data (`package-data`), set the version, add
   `"eudoxys"` to `keywords`, verify a non-editable install runs the tests.
2. Fix or explicitly document the known issues above that affect `Total`,
   `DG`, `Calibrate` and the CLI (#26, #27, #28, #30, #32); remove
   non-functional CLI verbs or implement them.
3. Clean up stale references in `loads/__init__.py` and `CLAUDE.md`; add
   re-exports of the public classes.
4. Add data READMEs for `caiso/`, `isone/`, `wecc/`.
5. Decide which open PRs (#19, #36, #38, #43) land before the release.

## Open questions

1. **Version number.** `1.0.0` (stable contract) or `0.1.0` with
   `Development Status :: 3 - Alpha` kept?
2. **Front end.** Is `Estimator` the supported prediction API and `Total`
   the training-data accessor, or are both public with overlapping roles?
3. **Large outputs.** Keep `wecc_estimate.csv.gz`, `node_estimate.csv.gz`,
   `county_dg.csv`, `examples/*.csv.gz` in the repo, ship them as release
   assets, or regenerate on demand? (`county_dg.csv` duplicates its `.gz`;
   `examples/` duplicates two `wecc/` files.)
4. **DG convention at the `Calibrate` boundary.** Accept `elec_dg_MW`
   (negative) directly, or keep positive `D` and document it?
5. **Open PRs.** Which of #19 (growth), #36 (normalize), #38 (folds),
   #43 (EIA DG) are in version 1?
6. **Transportation.** Implement for version 1, or declare it out of scope
   and drop the zero column?
7. **`isone/`.** Keep (for a future non-WECC validation) or remove?
