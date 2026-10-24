---
name: loads
description: >-
  US county-level hourly electric load modeling with eudoxys/loads: build
  residential, commercial, industrial and agricultural load, distributed
  (rooftop solar) generation and net load for a county and year from
  ResStock/ComStock, Census, OpenEI, NLR and NSRDB weather data; predict or
  sample other years with the TSGAM weather model; read the precomputed
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
places, call `loads` in an explicit mode, check what came back against the
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

1. **Python 3.12 and a clone.** `loads` pins `==3.12.*`. Install from a
   clone (`git clone https://github.com/eudoxys/loads && cd loads &&
   python3.12 -m venv .venv && . .venv/bin/activate && pip install -e .`):
   the precomputed WECC estimates in `loads/wecc/` are not installed by a
   non-editable `pip install` (the DG data files are).
2. **NSRDB credentials.** Every `Total` call fetches NSRDB weather. Without
   `~/.nsrdb/credentials.json` (`{"<email>": "<api_key>"}`) the `weather`
   package tries to open a sign-up page in a browser, which hangs headless
   agents. Only the user can register (https://developer.nlr.gov/signup/);
   never invent a key. Reading the precomputed WECC files needs no key.
3. **Cache folder.** `cache` defaults to a folder inside site-packages.
   `ls.configure()` points it at `$LOADS_CACHEDIR` or `~/.cache/eudoxys`
   and raises early if credentials are missing.
4. **Budget time.** First access to a county downloads several sources and
   fits a TSGAM model per target column: minutes per county, hours for a
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

Resolve -> fetch in an explicit mode -> validate -> use -> export with provenance.

```python
import loads.skill as ls

ls.configure()                                   # cache dir + credential check
c = ls.resolve("Alameda County, CA")             # -> County(state="CA", county="Alameda", ...)

df = ls.county_loads(c, 2020, sectors=True)      # total, sectors, DG, net + weather
rep = ls.validate(df, require_full_years=True)   # the loads contract, checked
rep.raise_if_failed()

facts = ls.summary(df, "elec_net_MW")            # energy MWh, peak, load factor
monthly = ls.energy(df, "MS")                    # *_MWh per month
ls.to_csv(df, "out/alameda_2020.csv.gz")         # + .meta.json provenance sidecar
```

Shell equivalent: `python3 -m loads.skill county "Alameda CA" 2020
--sectors -o out/alameda_2020.csv.gz` prints a JSON report including
validation; exit code 2 means the frame failed validation.

## Pick the mode deliberately

`loads.Total(state, county, ...)` changes behavior with `samples`. Most
mistakes with this package are a wrong mode. `ls.series` names them:

| Need                                  | `loads.skill`                                 | `loads.Total`                          | Output columns                     |
|---------------------------------------|-----------------------------------------------|----------------------------------------|------------------------------------|
| Reference ("actual") 2018 load        | `training(c)`                                 | `Total(st, co)`                        | weather + every sector, DG, total, net |
| Expected load for a year (weather-driven) | `series(c, 2021)`                         | `Total(..., date_range=idx, samples=0)` | X weather + one target            |
| One plausible realization             | `series(c, 2021, mode="sample")`              | `samples=1`                            | X + target (random AR draw)        |
| A high/low planning quantile          | `series(c, 2021, mode="percentile", samples=200, percentile=95)` | `samples=200, percentile=95` | X + target at that percentile (per hour, not a coherent trajectory) |
| An ensemble for uncertainty           | `series(c, 2021, mode="samples", samples=50)` | `samples=50, percentile=None`          | X + `sample_0..49`                 |

Facts that follow from the source:

- `samples=None` (the default) returns 2018 training data and **ignores
  `date_range`**. There is no `year` argument: `Total("CA", "Alameda",
  2020)` raises `TypeError`, and `loads print -Y 2020` silently prints 2018.
- Predict/sample modes return **only** the exogenous weather columns and the
  one target `Y` (plus `elec_dg_MW`, and `elec_net_MW` when `Y` is
  `elec_total_MW`, with `dg=True`). For total + DG + net + sectors in a year other than 2018,
  call once per target; `county_loads` does that and assembles them.
- `dg=True` adds the EIA-based `loads.dgen.DG` as `elec_dg_MW` (replacing
  the model's DG) and recomputes `elec_net_MW` where `elec_total_MW` is
  present; `county_loads(dg_source="eia")` does the same for the assembled
  frame.
- Predictable targets: `elec_total_MW`, `elec_residential_MW`,
  `elec_commercial_MW`, `elec_dg_MW` and their `nonelec_` analogues.
  Industrial and agricultural are flat at the 2018 level (no shape, no
  weather response); transportation is zero.
- The first 3 and last 3 hours of every predicted series are NaN (lag
  window). `edges="fill"` (default) copies the nearest hour, `"pad"` widens
  the request and trims, `"nan"` keeps them.
- A percentile series is the per-hour quantile across samples; its energy
  and peak are not the energy or peak of any realization. For peak or
  energy distributions, use `mode="samples"` and compute the statistic per
  sample.
- `Total` is not calibrated to EIA or any other reported total, in any
  year. Calibration is a separate step (below).

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
- no NaN except in the lag window; plausible weather ranges.

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
- uncertainty bands and peak distributions from sample ensembles;
- hold-out skill testing (`Estimator(county_st)`, cross-validated with
  `EstimatorConfig(fold=True)`, `Total.test`) and comparison with measured
  load imported with `loads.Normalize`;
- handing loads to GridLAB-D players, PyPSA/production-cost CSVs, or
  cvx-sd signal decomposition.

## Footguns

These fail silently or late. The full list with source references is in
[footguns.md](reference/footguns.md).

- **Wrong mode.** Training data returned where a year was intended (see
  above). Check `df.index.year.unique()` and `df.attrs["loadskill"]["mode"]`.
- **Which DG, which sign.** `elec_dg_MW` is the building-stock PV model by
  default, or EIA-861M small-scale solar with `Total(dg=True)` /
  `county_loads(dg_source="eia")` (zero, with a warning, outside the 13
  WECC states). Say which. `loads` frames and `loads.dgen.DG` use
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
- **`direct` vs `sum` totals.** `Total`'s own `elec_total_MW` model and the
  sum of separately predicted sector models differ by a few percent. Pick
  one per study (`county_loads(total=...)`).
- **`Total` vs `Estimator`.** Different TSGAM configurations, different
  numbers; `wecc_estimate` is built from `Estimator`. Use one per study.
- **Two location formats.** `Total`, `Residential`, ... take
  `state="CA", county="Alameda"`; `Estimator`, `Cluster`, `Calibrate`
  columns, `clusters.csv` and the WECC files use `"Alameda CA"`.
  `County.kwargs` and `County.county_st` give both.
- **`Normalize` sums.** All rows in an hour are added up (all meters
  without `groups`), so source values must be energy per interval;
  sub-hourly power readings need dividing by the readings per hour, and an
  hour with missing meters comes out low.
- **No growth in predictions.** `Units`/`Floorarea` can extrapolate growth,
  but `Total` predictions keep 2020 housing units and 2019 floor area for
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
- [`examples/uncertainty.py`](examples/uncertainty.py) — sample ensemble ->
  peak distribution and P10/P50/P90 hourly band.
- [`examples/offline_demo.py`](examples/offline_demo.py) — the helper
  pipeline on a synthetic `Total`-shaped frame; runs with no network.
