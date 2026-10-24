# Workflows

Recipes for composing `loads` into larger analyses. Each one: fetch in an
explicit mode, validate, then transform. All assume

```python
import pandas as pd
import loads.skill as ls
ls.configure()          # cache folder + NSRDB credential check
```

and Python 3.12 with a clone of `eudoxys/loads` installed (`pip install -e
.`). Before any sweep, run the recipe on one county and show the user the
timing and a summary. Recipe 1 needs no `configure()`, credentials or
network.

## 1. WECC counties 2018-2022: read the precomputed estimate

```python
places = [c.county_st for c in ls.counties(state="NV")]
gross = ls.wecc_estimate(places, [2021])            # MW, one column per county
dg = ls.wecc_dg(places, [2021])                     # <= 0, county_dg.csv.gz
net = gross + dg                                    # retail-sales-equivalent net load
state = net.sum(axis=1)
cp = ls.coincident_peak(net)                        # who drives the state peak (UTC)
monthly = ls.energy(net.rename(columns=lambda c: f"{c}_MW"), "MS")
```

- Gross load is `Estimator`-shaped and rescaled per UTC month to the
  county's EIA-861M retail allocation plus `county_dg.csv.gz`, so
  `gross + wecc_dg(scaled=False)` reproduces the monthly retail energy.
  `wecc_dg(scaled=True)` is the EIA-small-scale-solar-scaled DG (larger,
  e.g. ×3.2 for California in 2020); use it when the question is about
  behind-the-meter solar itself, and say which you used.
- No sectors, no weather, no uncertainty, one hourly realization, 2018–2022
  only. Use recipes 2–6 when the question needs those.
- Nodes: `ls.node_estimate(when=2021)` gives the WECC240 load nodes
  (uncalibrated; see footguns.md #30).
- Shell: `python3 -m loads.skill wecc --years 2021 -o wecc_2021.csv`
  (all counties) or with county names.

## 2. One county, one or more years

```python
c = ls.resolve("Maricopa County, AZ")
if c.ambiguous:
    print(f"warning: {c.county_st} is ambiguous in fips; loads cannot disambiguate")

df = ls.county_loads(c, [2019, 2020, 2021], sectors=True)   # total = Σ sectors
ls.validate(df, require_full_years=True).raise_if_failed()

print(ls.summary(df, "elec_total_MW"))
annual = ls.energy(df, "YS")                                   # MWh per year
peaks = ls.peaks(df, ["elec_total_MW", "elec_net_MW"], n=3)    # UTC times
local = ls.to_local(df, "America/Phoenix")                     # for reporting
ls.to_csv(df, "out/maricopa_2019_2021.csv.gz")
```

Choices to state in the write-up: `total="sum"` vs `"direct"`, `edges`,
the DG source, and that 2018 rows (if any) are training data.

Only the total (no sectors) is cheaper: `county_loads(c, years)` fits two
models (total, DG) instead of four.

DG: by default `elec_dg_MW` is the TSGAM prediction of the building-stock
rooftop PV. For DG that matches EIA's reported small-scale solar each
month (WECC states only; needs EIA access and NSRDB), use

```python
df = ls.county_loads(c, [2019, 2020, 2021], sectors=True, dg_source="eia")
```

which takes `elec_dg_MW` from `loads.dgen.DG` (what `Total(dg=True)`
merges) and fits one model fewer.

Load growth: predictions keep 2020 housing units and 2019 commercial floor
area in every year. To show growth, scale the predicted sector series, e.g.

```python
from loads import Units, Floorarea
g_res = Units(c.state, c.county, 2030) / Units(c.state, c.county, 2020)   # 1%/yr after 2024
g_com = (1 + Floorarea.GROWTH_RATE) ** (2030 - Floorarea.YEAR)             # 1.75%/yr from 2019
```

and recompute the total and net; record the rates in the provenance
(`ls.to_csv(..., extra={...})`).

## 3. Sweep a state or interconnection

```python
places = ls.counties(state="NV")            # or system="WECC", region="CAISO"
res = ls.batch(places, ls.county_loads, 2020,
               progress=lambda name, n, k: print(f"{n}/{k} {name}", flush=True))
print(f"{len(res.frames)} ok, {len(res.errors)} failed")
for name, err in res.errors.items():
    print("FAILED", name, err)

panel = res.column("elec_net_MW")           # one column per county
state_total = panel.sum(axis=1, min_count=1)
cp = ls.coincident_peak(panel)              # contribution at the state peak
```

- `batch` collects failures instead of aborting, and clears fitted models
  between counties (`clear_estimator_cache=True`) to bound memory.
- Make long sweeps resumable: write each county to its own file and skip
  files that already exist and validate. `loads`' own cache makes repeated
  fetches fast, but your assembled frames are not cached.
- Run long sweeps in the background with output to a log file; first
  access per county can take minutes.

```python
import os
def county_file(c, year):
    path = f"out/{year}/{c.state}_{c.county.replace(' ', '_')}.csv.gz"
    if os.path.exists(path):
        return ls.read_csv(path)
    df = ls.county_loads(c, year)
    ls.validate(df).raise_if_failed()
    ls.to_csv(df, path)
    return df

res = ls.batch(places, county_file, 2020)
```

## 4. Counties → network nodes

```python
nodes = (pd.read_csv("https://github.com/eudoxys/wecc240/raw/refs/heads/main/wecc240/gis/wecc240.csv")
           .rename(columns={"LAT": "lat", "LON": "lon"})
           .drop_duplicates("GEOHASH").set_index("GEOHASH"))   # node id -> lat/lon

places = ls.counties(system="WECC")
mapping = ls.nearest_nodes(places, nodes, max_km=300)
unmapped = mapping[mapping.node.isna()]          # report these

res = ls.batch(places, ls.series, 2020)          # predicted elec_total_MW
county_series = {k: v["elec_total_MW"] for k, v in res.frames.items()}
nodal = ls.allocate(county_series, mapping, strict=False)
print("unallocated MWh:", ls.conservation_error(county_series, nodal))
ls.to_csv(nodal, "out/wecc240_2020_total.csv.gz",
          extra={"mapping": "nearest centroid", "max_km": 300})
```

- Nearest-centroid is a placeholder for a real county→bus allocation. When
  the user has one (e.g. from substation load shares), pass
  `{"County ST": {"bus_a": 0.7, "bus_b": 0.3}}` to `allocate`.
- Reading `nodes` from GitHub needs network; in a sandbox ask for the file.
- For WECC240 in 2018–2022, `ls.node_estimate` already holds an
  (uncalibrated) allocation using in-county load buses; prefer it when its
  limits are acceptable.
- Report `conservation_error` and any unmapped or failed counties next to
  the nodal result.

## 5. Calibrate to known energy and peaks

Proportional, one target (e.g. a utility's reported annual sales for the
county):

```python
cal, k = ls.scale_to_energy(df, {"elec_total_MW": 12.3e6},          # MWh
                            start="2020-01-01", end="2020-12-31 23:00",
                            also_scale={"elec_total_MW": [c for c in df if c.startswith("elec_")
                                        and c not in ("elec_total_MW", "elec_dg_MW", "elec_net_MW")]})
ls.validate(cal).raise_if_failed()      # sector sum and net identity kept
```

Monthly, county share of EIA-861M state sales (needs the `eia` package
and network):

```python
from eia import HS861m
state = "NV"
months = pd.date_range("2020-01-01", "2020-12-01", freq="MS", tz="UTC")
state_mwh = pd.Series([HS861m(t.year, t.month).loc[state, "tot_energy_mwh"] for t in months],
                      index=months)
# share of each county in the modeled state total, per month
panel = res.column("elec_total_MW")                          # all counties in the state
share = panel.resample("MS").sum().div(panel.resample("MS").sum().sum(axis=1), axis=0)
cal = {name: ls.scale_monthly(frame, "elec_total_MW", state_mwh * share[name])[0]
       for name, frame in res.frames.items()}
```

Energy and peak together for one series (affine; holds the peak hour, moves
the minimum):

```python
y = ls.fit_energy_peak(df["elec_total_MW"], energy=12.3e6, peak=2450.0)
```

EIA retail sales are delivered energy net of behind-the-meter solar for
many customers; decide whether to match `elec_total_MW` or `elec_net_MW`
and say which. Industrial EIA sales are not comparable to the flat NLR
inventory without checking.

### Panel shaping to state energy and regional peaks (`Calibrate`)

When the targets are regional and coupled (every state's monthly energy
*and* the CAISO and WECC peaks), shape the whole panel at once with
`loads.calibrate.Calibrate` via `shape_to_targets`. The package's own WECC
targets and memberships for 2018–2022 are in `loads/_test/data/`
(see its README for sources and definitions):

```python
import os, loads
data = os.path.join(os.path.dirname(loads.__file__), "_test", "data")
def monthly(name):
    t = pd.read_csv(os.path.join(data, name), index_col=0)
    t.index = pd.to_datetime(t.index, utc=True)
    return t

month = ls.hourly_range(start="2020-08-01", end="2020-08-31 23:00")
X = ls.wecc_estimate(None, month)                    # gross load, all 407 counties
D = ls.wecc_dg(list(X.columns), month, scaled=True)  # <= 0, EIA-scaled rooftop PV
regions = pd.read_csv(os.path.join(data, "state_groups.csv"), index_col=0).reindex(X.columns)

out = ls.shape_to_targets(X, dg=D, energy=monthly("energy_target.csv"),
                          peak=monthly("peak_target.csv")[["CAISO", "WECC"]],
                          regions=regions, search=True,
                          progress=lambda done, total, info: print(f"{done}/{total}", end="\r"))
print(out.summary[["selection", "state_energy_max_abs_relative_error",
                   "caiso_peak_shortfall_fraction", "wecc_peak_shortfall_fraction"]])
shaped_net = out.net                                 # L - D_output, MW
```

- Energy targets are **net-load** MWh per state; peaks are net-load MW
  ceilings per region. `dg` is given in the `loads` convention (≤ 0) and
  converted; the program wants positive output.
- Each UTC month is a separate block with its own target row; the frame
  above is one month (88 solves; a few minutes for 407 counties). A year is
  twelve times that.
- The result is an affine shaping (scale and offset per county per month),
  not a proportional rescale. Report `out.summary.selection`,
  `out.states.shaped_error` and `out.regions` (target vs shaped peaks)
  with the result, and the validation numbers in
  `loads/_validate/README.md` if the question is about accuracy.
- With your own units (e.g. nodes), pass `states=` (units × states,
  fractions summing to 1) because the state can no longer be read from a
  `"County ST"` name.

## 6. Uncertainty and peaks

```python
ens = ls.series(c, 2020, mode="samples", samples=50)
S = ens.filter(like="sample_")
peak_dist = S.max()                       # peak of each realization (MW)
energy_dist = S.sum()                     # annual MWh of each realization
band = S.quantile([0.1, 0.5, 0.9], axis=1).T   # hourly P10/P50/P90 (not trajectories)
print(peak_dist.describe(), energy_dist.describe())
```

`mode="percentile"` is cheaper but only gives a per-hour envelope; never
report its maximum as "the P95 peak".

## 7. Measure model skill for a county

```python
from loads import Estimator
ho = Estimator(c.county_st)                    # 2018, every 5th day held out
h = ho[ho.status == "H"]
rmse = ((h.prediction - h.actual) ** 2).mean() ** 0.5
mape = ((h.prediction - h.actual).abs() / h.actual).mean() * 100
```

Cross-validated over all five 5-day folds (#38; five fits, so five times
the cost), with every 2018 row predicted by a model that did not see it:

```python
from loads.estimator import EstimatorConfig
cv = Estimator(c.county_st, config=EstimatorConfig(holdout="5d", fold=True))
folds = cv.attrs["folds"]                      # MAE, RMSE, MAPE per fold + "mean" row
print(folds.loc["mean"])
```

Report the fold mean and spread rather than a single holdout. For a quick
check, `sectors=["residential"]` in the config skips the national
commercial, industrial and agricultural downloads.

`Estimator` uses its own configuration (log space, no AR). For the `Total`
model, use `Total.test(state, county, holdout_index, X=[...], Y=...)` with
a holdout index such as the last week of each month (the upstream
convention: `idx[idx.month != (idx + pd.Timedelta(days=7)).month]`).

### Compare with measured load (`Normalize`)

To check the model against AMI, SCADA or utility data, import it with
`loads.Normalize`, then compare hourly net load over the hours both
cover. Example for hourly meter kWh with an hour-ending column and a
UTC-offset column (the layout of `loads/_test/ami.csv.gz`):

```python
import numpy as np
from loads import Normalize
measured = Normalize("ami.csv",
    timestamps={"date": pd.DatetimeIndex,
                "hour": lambda x: pd.TimedeltaIndex((np.array(x) - 1) * 3600e9),
                "tz_offset": lambda x: pd.TimedeltaIndex(np.array(x) * 3600e9)},
    mapping={"elec_net_MW": "kwh_delta"},       # metered deliveries are net of PV
    scales={"kwh_delta": 1e-3})                 # kWh per hour -> MW; all meters summed
ls.validate(measured)                           # hourly UTC, no gaps
```

Add `groups={"kwh_delta": "meter_id"}` (or a circuit column) for one
series per meter or circuit. See
[footguns.md](footguns.md#imported-data-normalize) for missing meters and
power-vs-energy readings.

## 8. Hand off to other tools

GridLAB-D player (kW, UTC):

```python
ls.to_player(df["elec_net_MW"], "alameda_net.player", scale=1e3)
```

PyPSA / production-cost models usually want naive timestamps and one column
per bus in MW:

```python
nodal.tz_convert("UTC").tz_localize(None).to_csv("loads-p_set.csv")
```

Tidy / database:

```python
ls.to_long(panel).to_parquet("county_loads.parquet")
```

Signal decomposition (e.g. `cvxgrp/cvx-sd-skill`): hourly series with
`delta = 3600` s; supply local *standard* time so the daily period is not
broken by DST:

```python
y = ls.to_local_standard(df, c.tzoffset)["elec_total_MW"].to_numpy()
```

## 9. End-use what-ifs with the raw stock data

`RESstock`/`COMstock` expose end uses per building type, e.g. gas space
heating that would be electrified:

```python
from loads import RESstock, Units
r = RESstock("CA", "Alameda", "RSD")          # W per housing unit, 2018
gas_heat_MW = r["gas_heating"] * Units("CA", "Alameda", 2020) / 1e6  # rough; all units as RSD
```

This scaling ignores the mix of building types; for a defensible estimate
weight each type by its stock `units` share the way `Residential` does, and
state the assumed heat-pump COP explicitly.

## 10. Report

When results go to a person, include: county list (and any ambiguous or
failed ones), years, mode (`prediction`/`sample`/`percentile`/training),
total convention (`direct`/`sum`), DG source (model or EIA), any growth
applied, edge handling, calibration targets, and the provenance sidecar. Quote the scope limits from
[methodology.md](methodology.md#not-promised) that matter for the question.
