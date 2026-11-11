---
name: loads
description: >-
  US county-level hourly electric load modeling with eudoxys/loads: build
  residential, commercial, industrial and agricultural load, distributed
  (rooftop solar) generation and net load for a county and year from
  ResStock/ComStock, Census, OpenEI, NLR and NSRDB weather data; estimate
  other years with the TSGAM weather model (`Estimator`); read the precomputed
  2018-2022 WECC county and WECC240 node estimates; validate, summarize,
  calibrate to state energy and regional peaks, aggregate counties onto
  network nodes, and export to downstream tools. Use when a task needs a
  realistic load shape, load forecast/backcast by weather, sector breakdown,
  net load, or nodal load profiles for US counties (best exercised for WECC,
  2018-2022), or when code calls `loads.Total`, `Residential`, `Commercial`,
  `Estimator`, `Calibrate` or `aggregate`.
allowed-tools: Read, Write, Edit, Bash(python3 -m loads.skill **), Bash(python -m loads.skill **)
---

`loads` turns public building-stock, census, inventory and weather data into
hourly county load, in MW, by sector, driven by the county's actual weather.
This skill puts it to work inside larger workflows. Use **`loads`** for every
number; use **`loads.skill`** (the package this file ships in) to resolve
places, call `loads` with the right front end, check what came back against the
package contract, summarize it, calibrate or aggregate it, and hand it on
with provenance.

`loads.skill` never changes the model. If a result looks wrong, the cause is
upstream data or `loads` itself; say so rather than patching numbers.

Locate the installed copy with
`python3 -c "import loads; print(loads.__file__)"`. The `loads` source is
short and well documented (https://www.eudoxys.com/loads); read the module
before relying on behavior this skill does not cover.

## Before the first call

Do these once, at workflow start. Skipping them fails late or never returns.

1. **Python 3.12.** `loads` pins `==3.12.*`. In a Python 3.12 environment,
   `pip install git+https://github.com/eudoxys/loads` (or `epm install
   loads`) installs the package, this skill and the precomputed WECC files
   (about 126 MB). Use a clone with `pip install -e .` to work on `loads`
   itself or to run its tests and validation, whose data is repository-only.
2. **NSRDB credentials.** Every `Estimator` call fetches NSRDB weather. Without
   `~/.nsrdb/credentials.json` (`{"<email>": "<api_key>"}`) the `weather`
   package tries to open a sign-up page in a browser, which hangs headless
   agents. Only the user can register (https://developer.nlr.gov/signup/);
   never invent a key. Reading the precomputed WECC files needs no key.
3. **Cache folder.** `cache` defaults to a folder inside site-packages.
   `ls.configure()` points it at `$LOADS_CACHEDIR` or `~/.cache/eudoxys`
   and raises early if credentials are missing.
4. **Budget time.** First access to a county downloads several sources and
   fits a TSGAM model per estimated column: minutes per county, hours for a
   state or interconnection sweep. Results are cached afterwards. Test on one
   county (Alameda CA is the package convention) before sweeping.

```bash
python3 -m loads.skill env      # cachedir + credentials status (JSON)
```

## Read before you compute: WECC 2018-2022

For WECC counties in 2018-2022 the repository already holds hourly results
that took hours to build. Prefer them when they answer the question:

```python
import loads.skill as ls

gross = ls.wecc_estimate(["Alameda CA", "Washoe NV"], 2021)   # MW, "County ST" columns
dg = ls.wecc_dg(["Alameda CA", "Washoe NV"], 2021)            # <= 0 (loads convention)
net = gross + dg                                              # monthly energy = EIA retail allocation
nodes = ls.node_estimate(when=2021)                           # WECC240 nodes, uncalibrated
```

`wecc_estimate` is gross load from `loads.estimator.Estimator` shapes,
rescaled per UTC month to the county's EIA-861M retail sales allocation plus
its rooftop PV. It has no sector breakdown, no weather columns, one
realization (no uncertainty), and only 2018-2022. When the question needs any
of those, build from the model below. Shell: `python3 -m loads.skill wecc
"Alameda CA" --years 2021 -o alameda.csv`. Details:
[workflows.md](reference/workflows.md#1-wecc-counties-2018-2022-read-the-precomputed-estimate).

## The loop

Resolve -> fetch with the right front end -> validate -> use -> export with provenance.

```python
import loads.skill as ls

ls.configure()                                   # cache dir + credential check
c = ls.resolve("Alameda County, CA")             # -> County(state="CA", county="Alameda", ...)

df = ls.county_loads(c, 2020, sectors=True, dg=True)  # sectors, total, DG, net + weather
rep = ls.validate(df, require_full_years=True)   # the loads contract, checked
rep.raise_if_failed()

facts = ls.summary(df, "elec_net_MW")            # energy MWh, peak, load factor
monthly = ls.energy(df, "MS")                    # *_MWh per month
ls.to_csv(df, "out/alameda_2020.csv.gz")         # + .meta.json provenance sidecar
```

Shell equivalent: `python3 -m loads.skill county "Alameda CA" 2020
--sectors --dg -o out/alameda_2020.csv.gz` prints a JSON report including
validation; exit code 2 means the frame failed validation.

## Pick the front end deliberately

`loads.Total` only sums the 2018 sectors; `loads.Estimator` is the
prediction API. Most mistakes with this package are using one where the
other was meant. `ls.training`, `ls.series` and `ls.county_loads` name them:

| Need                                  | `loads.skill`                                 | `loads`                                | Output columns                     |
|---------------------------------------|-----------------------------------------------|----------------------------------------|------------------------------------|
| Reference ("actual") 2018 load        | `training(c)`                                 | `Total(st, co)`                        | every sector + `elec_total_MW` (nothing else) |
| Expected load for a year (weather-driven) | `series(c, 2021)`                         | `Estimator("Alameda CA", [2021])`      | weather + `elec_total_MW`          |
| One sector for a year                 | `series(c, 2021, "elec_residential_MW")`      | `Estimator(..., config=EstimatorConfig(sectors=["residential"]))` | weather + the column |
| Total, sectors, DG and net for a year | `county_loads(c, 2021, sectors=True, dg=True)` | several `Estimator` calls + `DG.merge` | sectors, total, DG, net + weather  |

Facts that follow from the source:

- `Total(state, county, *, fuel="elec", refresh=False)` returns the 2018
  `elec_{sector}_MW` columns and `elec_total_MW`, their sum, and nothing
  more: no weather, no DG, no net load, no other year. There is no `year`
  argument: `Total("CA", "Alameda", 2020)` raises `TypeError`, and
  `loads print -Y 2020` silently prints 2018.
- `Estimator(county_st, years, *, config=None)` returns the
  `EstimatorConfig.weather` columns and the one `EstimatorConfig.enduse`
  column (default `elec_total_MW` over all four sectors). With
  `keep_actuals` (default) 2018 hours hold the 2018 sector loads. For total
  + sectors in a year other than 2018, call once per column;
  `county_loads` does that and assembles them.
- Neither has DG. `loads.dgen.DG` is the only DG: EIA-861M small-scale
  solar allocated to the county and shaped by weather. `DG.merge(frame,
  state, county)` adds `elec_dg_MW` and sets `elec_net_MW` where
  `elec_total_MW` is present; `county_loads(dg=True)` does the same.
- Estimable columns (`schema.PREDICTABLE_TARGETS`): `elec_total_MW`,
  `elec_residential_MW`, `elec_commercial_MW` and their `nonelec_`
  analogues. Industrial and agricultural are flat at the 2018 level (no
  shape, no weather response); transportation is zero.
- The first 3 hours of the first estimated year are NaN (weather lags).
  `edges="fill"` (default) copies the first valid hour, `"pad"` also
  estimates the previous year and trims it, `"nan"` keeps them.
- Estimates are deterministic; there is no sampling or percentile mode.
- Neither `Total` nor `Estimator` is calibrated to EIA or any other
  reported total, in any year. Calibration is a separate step (below).

## Contract to check, not assume

`loads` documents invariants; frames you assemble, edit or read back only
keep them if every step did. `ls.validate(df)` checks them on the frame you
got:

- hourly, tz-aware UTC `timestamp` index, no gaps or duplicates; 8760/8784
  rows per full year;
- `elec_dg_MW <= 0` (DG is a negative load);
- `elec_net_MW == elec_total_MW + elec_dg_MW`;
- `elec_total_MW == Σ elec_{sector}_MW` on `Total` frames, and
  `== baseload + cooling + heating` on sector-model frames;
- no NaN except in the estimator's lag window; plausible weather ranges.

Report validation failures to the user with the frame's provenance
(`df.attrs["loadskill"]`); do not drop columns or rows to make a check pass.

## Workflows

Read [workflows.md](reference/workflows.md) for complete recipes:

- WECC counties 2018-2022 from the precomputed estimate;
- one county, one or more years, with sector breakdown and net load;
- state or interconnection sweeps with `batch` (errors collected, memory
  bounded) and county panels;
- county -> bus/zone aggregation with `nearest_nodes` + `allocate`
  (fractional splits supported, energy conservation reported);
- calibration: proportional to a county's energy (`scale_to_energy`,
  `scale_monthly`), affine energy + peak (`fit_energy_peak`), and panel
  shaping to state energy and regional peak targets with
  `loads.calibrate.Calibrate` (`shape_to_targets`);
- hold-out skill testing (`Estimator(county_st)`, cross-validated with
  `EstimatorConfig(fold=True)`) and comparison with measured
  load imported with `loads.Normalize`;
- handing loads to GridLAB-D players, PyPSA/production-cost CSVs, or
  cvx-sd signal decomposition.

## Footguns

These fail silently or late. The full list with source references is in
[footguns.md](reference/footguns.md).

- **Wrong front end.** `Total` (2018 sectors) used where a year was
  intended (see above). Check `df.index.year.unique()` and
  `df.attrs["loadskill"]["mode"]`.
- **Which DG, which sign.** `elec_dg_MW` only comes from `loads.dgen.DG`
  (EIA-861M small-scale solar; zero, with a warning, outside the 13 WECC
  states). Say so. `loads` frames and `loads.dgen.DG` use
  `elec_dg_MW <= 0`; `Calibrate(dg=...)`, the bundled
  `loads/wecc/county_dg*.csv.gz` files and `dgen.compile` output use
  positive generation. `wecc_dg` and `shape_to_targets` convert.
- **`Calibrate` shapes, it does not rescale.** It fits a scale and an
  offset per unit per UTC month to *net-load* state energy and regional
  peak targets, needs at least one peak region, and rejects NaN. See
  [api.md](reference/api.md#calibrate).
- **Ambiguous county names.** `fips` has Baltimore city and Baltimore
  County, St. Louis city and County, several Virginia pairs. `loads` keys on
  `(state, county)` only and cannot tell them apart; `resolve()` sets
  `County.ambiguous`. Tell the user.
- **UTC everywhere.** Months, days and peaks from raw output (and
  `Calibrate`'s monthly blocks) are UTC. Convert (`to_local`,
  `to_local_standard`) before reporting local calendar quantities.
- **`direct` vs `sum` totals.** An `Estimator` model of `elec_total_MW` and
  the sum of separately estimated sector models differ by a few percent.
  Pick one per study (`county_loads(total=...)`).
- **Two location formats.** `Total`, `Residential`, ... take
  `state="CA", county="Alameda"`; `Estimator`, `Cluster`, `Calibrate`
  columns, `clusters.csv` and the WECC files use `"Alameda CA"`.
  `County.kwargs` and `County.county_st` give both.
- **`Normalize` sums.** All rows in an hour are added up (all meters
  without `groups`), so source values must be energy per interval;
  sub-hourly power readings need dividing by the readings per hour, and an
  hour with missing meters comes out low.
- **No growth in predictions.** `Units`/`Floorarea` can extrapolate growth,
  but `Estimator` estimates keep 2020 housing units and 2019 floor area for
  every year. Apply growth separately and state the rate.
- **Scope.** Large loads (data centers) and EV/transportation load are not
  modeled; industrial and agricultural load are flat annual averages. Say so
  when results feed decisions.

## Reference

- [data-model.md](reference/data-model.md) — columns, units, sign
  conventions, index, sectors, end-use collection, building-type codes.
- [api.md](reference/api.md) — every public `loads` class: verified
  signature, what it fetches, what it returns, caveats.
- [methodology.md](reference/methodology.md) — how the estimate is built
  (stock models, scaling, TSGAM, DG, calibration) and what is not promised.
- [workflows.md](reference/workflows.md) — end-to-end recipes for composing
  `loads` into larger analyses.
- [footguns.md](reference/footguns.md) — known rough edges, each traced to
  source, with the workaround.
- [operations.md](reference/operations.md) — data sources, credentials,
  caching, runtime, memory, offline behavior, CI.

## Worked examples

- [`examples/county_year.py`](examples/county_year.py) — one county, one
  year: fetch, validate, summarize, export (needs data access).
- [`examples/nodal_profiles.py`](examples/nodal_profiles.py) — sweep a
  state, map counties to buses, check conservation, write node CSVs.
- [`examples/offline_demo.py`](examples/offline_demo.py) — the helper
  pipeline on a synthetic county frame; runs with no network.
