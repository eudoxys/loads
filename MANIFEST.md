# MANIFEST

Map of the `eudoxys/loads` repository. Every tracked file is covered by
one row or glob below; check with `python .github/check_manifest.py`.
Update this file in the same PR that adds, moves, or deletes a file.

## Start here

1. `CLAUDE.md` — conventions, known rough edges, working rules
2. `DESIGN.md` — design, numbered decisions, planned work for version 1
3. `loads/__init__.py` — package docs (spec, "What is not promised", columns, data-flow diagram)
4. `loads/total.py` — `Total`, the core sector-sum + TSGAM model
5. `loads/estimator.py` — `Estimator`, the newer TSGAM front end used by the WECC estimate

## Task index

- Add a sector or data source: copy `loads/industry.py` (flat shape) or `loads/residential.py` (stock + scaling); wire it into `loads/total.py`; export in `loads/__init__.py`; add a test in `loads/_test/`; add rows here
- Change an output column: module docstring example, `loads/__init__.py` "Load data" section, `README.md`, `DESIGN.md` contracts table
- Add a CLI option or dataset: `loads/cli.py` (`_getdata`, parser), the class's annotated `__init__` argument (see `makeargs` in `CLAUDE.md`), `loads/__init__.py` Syntax section
- Change calibration: `loads/calibrate.py`; fast tests `loads/_test/test_calibrate_synthetic.py`; August 2020 test `loads/_test/test_calibrate.py`; re-run `loads/_validate/validate_calibrate*.py` and update `loads/_validate/README.md`
- Change estimator defaults (harmonics, holdout): `loads/estimator.py`; sweep with `loads/_explore/explore_estimator.py`; results in `loads/_explore/explore_estimator_clusters.csv`; review holdout folds for one county with `loads/_review/review_estimator_folds_marimo.py`
- Re-cluster counties: `loads/_explore/explore_clusters_marimo.py` writes `loads/clusters.csv`
- Regenerate WECC outputs: `loads/wecc/wecc_estimate.py` → `node_estimate.py`; DG scaling `loads/wecc/county_dg_scale.py`; monthly county energy `python3 -m loads.energy` (writes `loads/wecc/county_mwh.csv`, `county_cf.csv`). Hours of work: only when asked
- Fix a test: tests and the module they cover are paired in the tables below; `loads/_test/README.md` says what each downloads
- Change a behavior the agent skill documents: update `loads/skill/SKILL.md` and `loads/skill/reference/` (usually `api.md`, `footguns.md`) and `loads/_test/test_skill_loads_api.py` in the same PR
- Update docs: docstrings, then `make docs` (output `docs/` is not committed)
- Release: `pyproject.toml` version and keywords; `DESIGN.md` "Release (version 1)"; the eudoxys-package skill checklist

## Package

| Path | Purpose | Notes |
|---|---|---|
| `loads/__init__.py` | package docs, module list | pdoc landing page; no re-exports yet (see `DESIGN.md`) |
| `loads/cli.py` | `loads` command, `main()` | entry point `loads`; `viewer`/`test`/`help`/`info` not functional |
| `loads/resstock.py` | `RESstock`: raw NREL ResStock 2018 end uses by building type | downloads OEDI S3; no direct test |
| `loads/comstock.py` | `COMstock`: raw NREL ComStock 2018 end uses by building type | downloads OEDI S3; no direct test |
| `loads/units.py` | `Units`: Census housing units (a `float`) | scales residential |
| `loads/floorarea.py` | `Floorarea`: OpenEI commercial floor area | scales commercial |
| `loads/residential.py` | `Residential`: ResStock → `elec_*_MW`/`nonelec_*_MW` | cache `R.csv.gz` v1 |
| `loads/commercial.py` | `Commercial`: ComStock → `elec_*_MW`/`nonelec_*_MW` | cache `C.csv.gz` v2 |
| `loads/industry.py` | `Industry`: NREL county industrial energy, flat shape | 2019 data |
| `loads/agriculture.py` | `Agriculture`: NREL county agricultural energy, flat shape | 2019 data |
| `loads/transportation.py` | `Transportation`: stub | raises `NotImplementedError`; `Total` uses 0 |
| `loads/dgen.py` | `DG` hourly county DG from EIA-861M small-scale PV, `DG.merge`, `SmallScaleSolar`; `compile()` writes a wide county file | downloads EIA via `eia.Form861m`; reads `wecc/county_mwh.csv` and, for `profile="dgen"`, `wecc/county_dg.csv.gz`; used by `Total(dg=True)` |
| `loads/_solar_estimator.py` | `SolarEstimator` (private) | not used by `DG` default path |
| `loads/total.py` | `Total`: 2018 sector sum, TSGAM fit/predict/sample | core model; cache `T_elec_1h_training.csv.gz` v2 |
| `loads/estimator.py` | `Estimator`, `EstimatorConfig`: TSGAM by `"County ST"` | tested by `_test/test_estimator.py` |
| `loads/energy.py` | `Energy`: periodic county energy (MWh); `__main__` writes `wecc/county_mwh.csv`, `county_cf.csv` | tested by `_test/test_energy.py` (stubbed `Total`) |
| `loads/calibrate.py` | `Calibrate`: convex net-load shaping to state energy + regional peaks (cvxpy) | tested by `_test/test_calibrate*.py` |
| `loads/cluster.py` | `Cluster`: SVD + k-means of county loads → medoids | used by `_explore/explore_clusters*.py` |
| `loads/normalize.py` | `Normalize`: imported (e.g. AMI) data → hourly `elec_*_MW` with optional groups and weather | tested by `_test/test_normalize.py` |
| `loads/aggregate.py` | `Aggregator`, `aggregate()`: counties → WECC240 nodes | reads `eudoxys/wecc240` over the network; see issue #15 |
| `loads/clusters.csv` | county → medoid map (`county_st,medoid`), k=6 on `elec_total_MW` | curated; written by `_explore/explore_clusters_marimo.py` |
| `loads/.gitignore` | ignores cache and scratch output | |

## Agent skill (`loads/skill/`)

The `loads.skill` subpackage: an agent skill for users of `loads` plus its
helpers. Conventions in `CLAUDE.md` ("Agent skill").

| Path | Purpose | Notes |
|---|---|---|
| `loads/skill/SKILL.md` | skill entry point: setup, the loop, modes, contract, footguns | read first for skill work |
| `loads/skill/reference/*.md` | data model, verified API, methodology, workflows, footguns, operations | must match the code; guarded by `_test/test_skill_loads_api.py` |
| `loads/skill/__init__.py` | `loads.skill` docs and re-exports | |
| `loads/skill/__main__.py`, `loads/skill/cli.py` | `python3 -m loads.skill` (JSON on stdout) | tested by `_test/test_skill_locations_export.py`, `test_skill_wecc.py` |
| `loads/skill/fetch.py` | explicit `Total` modes, `county_loads`, `batch`, `configure` | tested by `_test/test_skill_fetch_offline.py` (stubbed `Total`) |
| `loads/skill/calibrate.py` | proportional scaling, `fit_energy_peak`, `shape_to_targets` (`Calibrate` front end) | tested by `_test/test_skill_summarize_calibrate_aggregate.py` |
| `loads/skill/wecc.py` | readers for `loads/wecc/` estimates and DG | tested by `_test/test_skill_wecc.py` |
| `loads/skill/validate.py` | contract checks | tested by `_test/test_skill_validate.py` |
| `loads/skill/aggregate.py` | county → node allocation (`nearest_nodes`, `allocate`) | offline |
| `loads/skill/export.py` | CSV / GridLAB-D player export with `.meta.json` provenance | offline |
| `loads/skill/locations.py` | place names → `County` (`resolve`, `counties`) | offline (`fips`) |
| `loads/skill/schema.py` | column vocabulary and constants copied from `loads` | checked by `_test/test_skill_loads_api.py` |
| `loads/skill/summarize.py` | energy, peaks, load factor, profiles | offline |
| `loads/skill/timeaxis.py` | hourly UTC ranges, local-time conversion | offline |
| `loads/skill/examples/*.py` | worked examples; `offline_demo.py` runs without network | `offline_demo.py` run by `_test/test_skill_examples.py` |

## WECC estimate (`loads/wecc/`)

Maintenance scripts and their curated or generated data. Run from the folder
(`python3 loads/wecc/<script>.py`); they are not importable modules.

| Path | Purpose | Notes |
|---|---|---|
| `loads/wecc/wecc_estimate.py` | hourly 2018–2022 calibrated load of every WECC county | hours; writes `wecc_estimate.csv.gz` |
| `loads/wecc/wecc_estimate.csv.gz` | output of `wecc_estimate.py` (MW, `County ST` columns) | generated; 65 MB, don't read |
| `loads/wecc/node_estimate.py` | WECC240 node loads from the county estimate cache | writes `node_estimate*.csv*` |
| `loads/wecc/node_estimate.csv.gz` | node hourly load (uncalibrated) | generated; 21 MB, don't read |
| `loads/wecc/node_estimate_cf.csv` | county → node contribution factors | generated by `node_estimate.py` |
| `loads/wecc/county_dg_scale.py` | scales county PV to EIA small-scale solar | writes `county_dg_scaled.csv.gz`, `county_dg_scaling.csv` |
| `loads/wecc/county_dg_scaled.csv.gz` | county PV scaled by state/year (MW, positive) | generated; 22 MB, use `head`; read by calibration test/validation |
| `loads/wecc/county_dg_scaling.csv` | state × year PV scale factors | generated by `county_dg_scale.py` |
| `loads/wecc/eia_smallscale_pv.csv` | EIA EPA Table 3.21 small-scale PV GWh by state, 2018–2022 | curated input to `county_dg_scale.py` |
| `loads/wecc/county_dg.csv` | county rooftop PV (MW, positive) | generated from `dgen.csv.gz` by the former nodal `dgen.compile()` (removed in PR #43); read by `county_dg_scale.py`; 82 MB, don't read |
| `loads/wecc/county_dg.csv.gz` | compressed copy of `county_dg.csv` | hourly shapes for `DG(profile="dgen")`; read by `wecc_estimate.py`; 18 MB, don't read |
| `loads/wecc/dgen.csv.gz` | NREL dGen nodal DG | source of `county_dg.csv`; no longer read by package code; 13 MB, don't read |
| `loads/wecc/county_mwh.csv` | monthly EIA 861M retail MWh allocated to counties | generated by `python3 -m loads.energy` |
| `loads/wecc/county_cf.csv` | county share of state monthly energy | generated by `python3 -m loads.energy` |

## Reference data

| Path | Purpose | Notes |
|---|---|---|
| `loads/caiso/*.csv` | CAISO reported hourly load 2019–2022 (PT, hour ending) | curated; validation reference; 0.5–0.9 MB each; no README yet |
| `loads/isone/*.xlsx` | ISO-NE SMD hourly 2020–2022 | curated; 8 MB each, don't read; not referenced by code |

## Tests, validation, exploration, review

| Path | Purpose | Notes |
|---|---|---|
| `loads/_test/README.md` | how to run tests, what they download | |
| `loads/_test/conftest.py` | cache location from `LOADS_CACHEDIR` | |
| `loads/_test/test_calibrate_synthetic.py` | `Calibrate` on a small synthetic system | fast, offline |
| `loads/_test/test_calibrate.py` | `Calibrate` on all WECC counties, August 2020 | network; skipped unless the cache holds the inputs |
| `loads/_test/test_energy.py` | `Energy` with a stubbed `Total` | fast, offline |
| `loads/_test/test_estimator.py` | `Estimator` holdout and year handling | network (weather, stock data) |
| `loads/_test/test_skill_*.py` | `loads.skill` tests; `test_skill_loads_api.py` pins documented `loads` behavior | offline except `test_skill_network.py` (`LOADS_TEST_SKILL=1`) |
| `loads/_test/skill_synthetic.py` | synthetic `Total`-shaped frames for the skill tests | |
| `loads/_test/test_normalize.py` | `Normalize` sources, groupings, weather merge | `test_nogroups` needs NSRDB (weather) |
| `loads/_test/ami.csv.gz` | anonymized hourly AMI meter data for `test_normalize.py` | curated; 44 MB gzip, don't open |
| `loads/_test/make_data.py` | builds `ami.csv.gz` from a raw AMI export (anonymizes ids) | needs the raw file; not a test |
| `loads/_test/data/README.md` | provenance of test data | |
| `loads/_test/data/*_target.csv` | monthly state energy and CAISO/WECC peak targets | curated |
| `loads/_test/data/state_groups.csv` | county CAISO/WECC membership (0–1) | curated |
| `loads/_test/data/WECC_*_2018-2022.csv` | cleaned EIA-930 BA/WECC/CAISO hourly load | curated; 2.6–7.3 MB, use `head` |
| `loads/_validate/README.md` | validation question, inputs, procedure, results | update numbers when the model changes |
| `loads/_validate/validate_calibrate.py` | builds 2020 inputs and calibration in the cache | hours on an empty cache |
| `loads/_validate/validate_calibrate_marimo.py` | calibrated 2020 CAISO load vs reported | `marimo run` |
| `loads/_validate/validate_estimator_marimo.py` | estimator holdout/harmonics by county | `marimo run` |
| `loads/_explore/README.md` | what each exploration produced | |
| `loads/_explore/explore_clusters.py` | medoids for k=2–10 on every `Total` column | writes `explore_clusters.csv` |
| `loads/_explore/explore_clusters.csv` | output of `explore_clusters.py` | generated; 1.7 MB, use `head` |
| `loads/_explore/explore_clusters_marimo.py` | choose clustering; saves `loads/clusters.csv` | `marimo run` |
| `loads/_explore/explore_estimator.py` | harmonic/holdout sweep on medoids | resumable; writes `explore_estimator*.csv` |
| `loads/_explore/explore_estimator.csv` | sweep results | generated |
| `loads/_explore/explore_estimator_clusters.csv` | best parsimonious harmonics per medoid and metric | generated; read by `wecc/wecc_estimate.py` |
| `loads/_explore/explore_estimator_marimo.py` | review the sweep | `marimo run` |
| `loads/_explore/explore_calibrate_marimo.py` | calibration weight sensitivity, August 2020 | `marimo run` |
| `loads/_review/review_loads.py` | review one county's `Total` | marimo |
| `loads/_review/review_commercial_marimo.py` | review `Commercial` | marimo |
| `loads/_review/review_wecc_estimate_marimo.py` | view `wecc/wecc_estimate.csv.gz` | marimo |
| `loads/_review/review_node_estimate_marimo.py` | view `wecc/node_estimate.csv.gz` | marimo |
| `loads/_review/review_estimator_folds_marimo.py` | `Estimator` holdout fold results (`fold=True`) for any state and county | `marimo run`; fits `N` models, needs NSRDB credentials |

## Examples

| Path | Purpose | Notes |
|---|---|---|
| `examples/county_total.py` | marimo notebook: calibrated WECC county totals | |
| `examples/county_total.csv.gz` | its output | generated; 54 MB, don't read |
| `examples/county_cf.csv` | input copy | identical to `loads/wecc/county_cf.csv` |
| `examples/county_dg.csv.gz` | input copy | identical to `loads/wecc/county_dg.csv.gz`; 18 MB |
| `examples/__marimo__/session/notebook.py.json` | marimo session state | don't read |

## Repository

| Path | Purpose | Notes |
|---|---|---|
| `README.md` | user overview, install, maintenance | |
| `CLAUDE.md` | assistant guidance | |
| `DESIGN.md` | package design | |
| `MANIFEST.md` | this file | |
| `TODO.md` | roadmap | |
| `pyproject.toml` | packaging | version here; `package-data` is `*.py` plus the skill's markdown (no data files) |
| `requirements.txt` | dependencies (dynamic) | sibling packages via `git+` |
| `Makefile` | `make docs` | `test` target is broken (no `./test/`) |
| `LICENSE` | MIT | |
| `COPYRIGHT.md` | copyright and DOE Office of Electricity acknowledgment | |
| `.gitignore` | Python ignores | |
| `.gitattributes` | line endings | |
| `.github/workflows/validate.yaml` | CI: pip install, pylint, pytest | non-editable install |
| `.github/workflows/deploy-pages.yaml` | CI: `make docs` → GitHub Pages | |
| `.github/workflows/assign-issues.yaml` | assigns new and unassigned issues to the owner | |
| `.github/check_manifest.py` | checks this file against `git ls-files` | |

## Don't read

`docs/` (generated, not committed), `.venv/`, `.cache*`, `tests/`, `tsgam_test/`,
`**/__marimo__/` session files, and the data files marked "don't read" above
(use `head` or `pandas.read_csv(..., nrows=5)`).
