# Data model

What a `loads` frame contains, in what units and conventions. Verified
against the `loads` source in this repository;
`loads/_test/test_skill_loads_api.py` guards the parts that can be checked
without data.

## Frames are DataFrames

Every accessor (`RESstock`, `COMstock`, `Residential`, `Commercial`,
`Industry`, `Agriculture`, `Total`, `Calibrate`, `Energy`, `Estimator`,
`DG`, `Aggregator`) subclasses `pd.DataFrame` and does all its work in
`__init__`. Constructing one *is* the computation (and the download, the
first time). `Units` subclasses `float` (housing units for a county/year).

Wrap results in `pd.DataFrame(...)` before heavy manipulation if you want
to shed the subclass; `loads.skill` does this.

## Index

- Name `timestamp`, tz-aware **UTC**, hourly, sorted, unique.
- 8760 rows for a normal year, 8784 for a leap year.
- ResStock/ComStock and the `Total` training frame are **2018**
  (`Total.TRAINING_YEAR`). Industry/agriculture inventories are 2019 but
  have no time shape.
- Predicted/sampled series have NaN in the first 3 and last 3 rows (the
  `±3 h` exogenous lag window of `Total.TSGAM_CONFIG`).
- Local time is never applied. `fips` gives each county a standard-time
  offset (`TZOFFSET`) and a DST flag; `loads.Cluster` rolls by `TZOFFSET`.

## Units and naming

All load columns are average power over the hour in **MW**; the column
name ends `_MW`. Summing an hourly MW column gives **MWh**. Weather:

| column             | unit | meaning                         |
|--------------------|------|---------------------------------|
| `temperature_degF` | °F   | dry-bulb outdoor air            |
| `humidity_pc`      | %    | relative humidity               |
| `global_Wpms`      | W/m² | global horizontal irradiance    |
| `direct_Wpms`      | W/m² | direct normal irradiance        |
| `diffuse_Wpms`     | W/m² | diffuse horizontal irradiance   |

### Sector-model frames (`Residential`, `Commercial`, `Industry`, `Agriculture`)

`{elec|nonelec}_{category}_MW` with categories:

- `baseload`, `cooling`, `heating` — end uses collected from the stock data
  (`Residential.COLLECT`, `Commercial.COLLECT` list the source end uses);
- `total` — `baseload + cooling + heating` (recomputed, so it holds exactly);
- `dg` (electric only) — distributed generation, **negative**;
- `net` (electric only) — `total + dg`, i.e. `total - |dg|`.

`baseload` is every end use other than space cooling and heating
(lighting, appliances, plug loads, refrigeration, pumps, water heating);
`cooling`/`heating` are the space-conditioning end uses. `nonelec` is gas,
oil, propane (`lng_`), wood, district and other fuels expressed as MW of
energy use. Industry/agriculture put everything in `baseload` (flat), with
always-zero cooling/heating/DG columns.

Raw stock frames (`RESstock`, `COMstock`) use `{fuel}_{enduse}` names
(`elec_`, `gas_`, `oil_`, `lng_`, `wood_`, `district_`, `other_`) in W per
housing unit (ResStock) or W/sf (ComStock), plus `units` or `floor_area`.

### `Total` frames

Training frame (`samples=None`), one row per hour of 2018:

| column | meaning |
|---|---|
| weather columns | NSRDB 2018 weather for the county centroid |
| `elec_residential_MW` | `Residential(...)["elec_total_MW"]` |
| `elec_commercial_MW` | `Commercial(...)["elec_total_MW"]` |
| `elec_industrial_MW` | `Industry(...)` net, flat |
| `elec_agricultural_MW` | `Agriculture(...)` net, flat |
| `elec_transportation_MW` | 0 (not modeled) |
| `elec_dg_MW` | `-(|res dg| + |com dg|)`, ≤ 0 |
| `elec_total_MW` | sum of the five sector columns (DG excluded) |
| `elec_net_MW` | `elec_total_MW + elec_dg_MW` |

With `Y="nonelec_..."` the training frame is built with `nonelec_` columns
instead and has no DG.

Prediction/sample frames contain only the exogenous `X` columns and `Y`
(or `sample_0..n-1`). See [api.md](api.md#total).

## Invariants

What should hold, and what `ls.validate` checks:

1. complete hourly UTC coverage of the requested period;
2. `elec_total_MW = Σ sectors` (Total) / `= baseload + cooling + heating`
   (sector models);
3. `elec_dg_MW ≤ 0`;
4. `elec_net_MW = elec_total_MW + elec_dg_MW`;
5. loads other than DG and net are non-negative.

The training frame satisfies (2)–(4) (the total excludes `_dg_` columns).
Check rather than assume: frames you assemble yourself (e.g. a predicted
total with a predicted DG) only satisfy (4) if you compute net from them,
and calibrated or rescaled frames only if the same factor was applied to
every part.

## Sign conventions outside `Total`

| where | DG sign |
|---|---|
| `Total`, `Residential`, `Commercial`, `loads.skill` frames (`elec_dg_MW`) | ≤ 0 (negative load) |
| `Calibrate(dg=...)`, `Calibrate.net = L − D` | ≥ 0 (generation) |
| `loads/wecc/county_dg*.csv.gz`, `DG(...)` (column still named `elec_dg_MW`) | ≥ 0 (generation) |
| `ls.wecc_dg(convention="load")` (default) | ≤ 0 |

## Precomputed WECC files (`loads/wecc/`)

Hourly UTC (hour beginning), 2018–2022, `"County ST"` columns unless noted:

| file | values |
|---|---|
| `wecc_estimate.csv.gz` | gross load (MW) of 407 counties, 4 decimals; monthly energy = `county_mwh.csv` + `county_dg.csv.gz` |
| `node_estimate.csv.gz` | uncalibrated gross load (MW) of WECC240 load nodes, geohash columns |
| `county_dg.csv.gz`, `county_dg_scaled.csv.gz` | rooftop PV output (MW, ≥ 0), from 2018-01-01 07:00 UTC |
| `county_mwh.csv` | monthly EIA-861M retail MWh allocated to counties (`Jan 2018` row labels) |
| `county_cf.csv` | monthly county contribution factors used for that allocation |

## Building types

Residential (`RESstock.BUILDING_TYPES`): `RSD` single-family detached,
`RSA` single-family attached, `RSM` multi-family 2–4 units, `RMM`
multi-family 5+ units, `RMH` mobile home.

Commercial (`COMstock.BUILDING_TYPES`): `CLF` full-service restaurant, `CLH`
hospital, `CLL` large hotel, `CLO` large office, `CSH` outpatient, `CMO`
medium office, `CSE` primary school, `CSF` quick-service restaurant, `CSR`
retail standalone, `CMR` retail strip mall, `CME` secondary school, `CSL`
small hotel, `CSO` small office, `CMW` warehouse.

Some building types have no data in some counties; `loads` returns zeros
and logs at DEBUG rather than raising.

## Locations

- `state`: two-letter postal code. `county`: `fips` spelling without
  "County"/"Parish" (`"Alameda"`, `"Doña Ana"`, `"East Baton Rouge"`).
- `Estimator`, `Cluster`, `loads/clusters.csv`, `Calibrate` columns and the
  `loads/wecc/` files use one string `"Alameda CA"`.
- `fips.Counties` holds duplicate `(state, county)` keys for independent
  cities that share a county's name (MD Baltimore, MO St. Louis, VA Fairfax,
  Franklin, Richmond, Roanoke). `loads` cannot distinguish them.
- `fips` also gives `LAT`/`LON` (centroid used for weather and aggregation),
  `GEOHASH`, `SYSTEM` (`WECC`, `EAST`, `ERCOT`, `AK`, `HI`), `RO`, `REGION`.

`ls.resolve` returns all of this as a `County`.
