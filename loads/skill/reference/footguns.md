# Footguns

Rough edges in `loads`, each traced to the source in this repository, with
the workaround. Items marked **[tested]** are reproduced offline in
`loads/_test/test_skill_loads_api.py`; if such a test starts failing,
`loads` changed: update this file in the same change, do not just delete the
test.

Tracking: #26 (items 1, 3), #29 (16), #32 (7, 9), #33 (17), #15
(22), #12 (DG sign, lag trimming), all at
https://github.com/eudoxys/loads/issues. #27 and #28 described the
calibration API that the `Calibrate` rewrite (#20) replaced, and #30
described the `DG` file reader that #43 replaced; #31 and #44 are fixed. Check whether an issue is closed before relying on a workaround
below.

Do not silently "fix" these in `loads` from inside a workflow. Work around
them and mention them to the user when they affect results; offer to check
the tracking issues above or open a new one.

## Modes and arguments

1. **`Total` has no `year`.** `Total("CA","Alameda",2020)`, a pattern
   older docs and notebooks used, raises `TypeError` **[tested]**. Pass
   `date_range=` and `samples=`. → `ls.series` / `county_loads`.

2. **Default `samples=None` returns 2018 training data and ignores
   `date_range`.** Asking for 2021 without `samples` silently gives 2018.
   → always pass `samples`, or use `loads.skill` modes and check
   `df.index.year`.

3. **CLI `-Y` is dropped for totals.** `Total.makeargs` keeps only
   annotated `__init__` args; `year` is not one **[tested]**. `loads print
   -S CA -C Alameda -Y 2020` prints 2018 (the CLI docs now say so). →
   `python3 -m loads.skill county`.

4. **Prediction frames hold one target.** `samples>=0` returns `X` + `Y`
   only (plus the EIA DG and net with `dg=True`). Sector columns and the
   model DG need separate calls. → `county_loads`.

5. **Industrial/agricultural cannot be predicted by default.** They are
   absent from `EXOGENOUS_VARIABLES` (`KeyError` without `X`), and are flat
   anyway. → copy the 2018 level (`county_loads(sectors=True)` does).

6. **Percentile ≠ realization.** `samples=n, percentile=p` gives the
   per-hour p-th percentile; its daily energy/peak are not those of any
   sample and overstate coincident peaks. → `mode="samples"` and compute
   statistics per sample.

7. **`samples=1` is random.** Upstream `aggregate()` uses it, so nodal
   aggregates differ run to run (TSGAM sampling is not seeded in
   `Total.TSGAM_CONFIG`: `random_state=None`). → use predictions for
   expected values; sample deliberately and record that you did.

8. **Lag-window NaN.** First/last 3 hours of every prediction are NaN.
   Downstream tools that reject NaN (players, solvers) fail or hold stale
   values. → `edges="fill"`/`"pad"`; `validate` reports edge NaN.

9. **Non-contiguous date ranges are bridged.** `Total` treats the whole
   `date_range` as one series; `[2019, 2021]` is fitted as if Dec 31 2019
   were followed by Jan 1 2021 (AR and lags cross the gap). →
   `ls.series` predicts each contiguous block separately.

10. **`Estimator` vs `Total`.** Different TSGAM configs (Estimator: log
    space, no AR, 4/4/6 harmonics, outlier model; Total: linear, AR 1–9,
    4/4/12 harmonics), different results, different location argument
    (`"Alameda CA"`). `Estimator` cannot model DG or net (log of ≤ 0).
    `wecc_estimate.csv.gz` is `Estimator`-based. → pick one per study and
    record it.

## Calibration and energy

11. **`Calibrate` takes DG as positive output.** `dg` must be ≥ 0 (it is
    subtracted from load); passing an `elec_dg_MW` panel raises
    `CalibrationError` **[tested]**. Its `load` is gross load
    (`elec_total_MW`), and its `energy` targets are *net-load* (load − DG)
    energy. → `ls.shape_to_targets(dg=..., dg_convention="load")`
    negates for you; the bundled WECC DG files are already positive
    (`dg_convention="output"`).

12. **`Calibrate` is an affine shaping per UTC month, not a rescale.**
    Each unit gets a scale and an offset per calendar month (UTC), chosen
    to meet coupled state energy and regional peak targets while limiting
    shape change **[tested]**. Months are solved independently (small steps
    at month boundaries), every month in the frame needs a target row, and
    with `search=True` each month costs 88 solves (two regions). → for one
    county's own energy use `scale_to_energy`/`scale_monthly`
    (proportional); check `.summary.selection` and `.states.shaped_error`
    after shaping.

13. **`Calibrate` needs a peak region and clean input.** `peak={}` raises
    `KeyError` while building the region table **[tested]**, so
    energy-only shaping is not available; NaN (e.g. `Total`'s lag-window
    edges) raises `CalibrationError` **[tested]**; columns without a
    `"County ST"` name need `states=`. → `shape_to_targets` checks all three
    up front; for energy only, use `scale_monthly`.

14. **The old calibration API is gone.** `fit_load`, `integrate`,
    `Calibrate.load`, `Calibrate.solar` and the `start`/`end`/`scale`/
    `offset` arguments were removed with the rewrite (#20) **[tested]**;
    code written against them fails at import or call. → port to
    `Calibrate(load, energy=..., peak=..., dg=...)` or the `ls.scale_*`
    helpers; `ls.fit_energy_peak` reproduces `fit_load`'s energy + peak fit.

15. **Nothing in `Total` is calibrated.** Neither the 2018 training frame
    nor predictions are adjusted to EIA sales; scaling only enters through
    Census housing units and OpenEI floor area. Only the DG can be
    EIA-based (`dg=True`), and then net load mixes uncalibrated load with
    EIA-matched DG. → calibrate explicitly
    (above), or for WECC 2018–2022 use `wecc_estimate`, whose monthly
    energy matches EIA-861M retail allocations plus rooftop PV; state which
    figures you matched.

16. **`Energy` needs a year pair.** An int `year` fails at `min(year)`
    **[tested]**. Its cache key ignores the county list (second call for a
    different county in the same state/period returns the first result).
    A county whose `Total` fails is omitted with a warning, so check the
    columns you got. → `Energy(state, counties, [y0, y1], refresh=True)` or
    `ls.energy(frame, "MS")`.

## Locations and data

17. **Duplicate county names.** `fips` lists independent cities and
    counties with the same name (MD Baltimore, MO St. Louis, VA Fairfax,
    Franklin, Richmond, Roanoke). `loads` keys on `(state, county)` and
    cannot select one. → `resolve()` sets `County.ambiguous`; tell the user.

18. **Two location formats.** `Total`/sector classes: `state=, county=`.
    `Estimator`, `Cluster`, CSV maps: `"County ST"`.

19. **Two DGs, and `Total(dg=True)` changes which one you get.** By
    default `elec_dg_MW` is the ResStock/ComStock rooftop PV (training) or
    its TSGAM prediction; `dg=True` (#43) replaces it with `loads.dgen.DG`,
    EIA-861M small-scale solar allocated by county energy share, which is
    several times larger in California. `DG` gives **zero with only a
    warning** for counties outside the 13 WECC states **[tested]**, needs
    EIA access, and NaN for months EIA has not published. →
    `county_loads(dg_source="model"|"eia")`, and report which DG you used;
    don't mix them across counties or years. (The earlier footgun about a
    cwd-relative, positive-valued `DG` file reader is gone with #43.)

19b. **Load growth (#19) is not in `Total`.** `Units` (1%/yr after
    2024; before 2020 only with `backcast=True`) and `Floorarea`
    (1.75%/yr from 2019) now extrapolate, but `Residential` and `Commercial`
    still request their 2018/2019 bases, so a `Total` prediction for 2030 has
    2020 housing units and 2019 floor area **[tested]**. → apply growth to
    the predicted sector series yourself and state the rate.

20. **`Industry`/`Agriculture` `loadshape` must average 1.0** (values are
    `shape × average MW`) and is ignored unless both `state` and `county`
    are given. Counties absent from the NREL inventories now get zero load;
    caches built before `608b9c4` may still hold the previous county's
    load (e.g. San Juan CO had Saguache CO's agriculture). → rebuild with
    `refresh=True` if your cache predates that commit.

21. **Missing building types become zeros** (logged at DEBUG). A county
    with suspiciously low commercial load may lack ComStock coverage. →
    enable DEBUG logging for the `loads` modules when results look thin.

22. **`aggregate()` is WECC-only, nearest-node only, sample-based**, caches
    by year+column (changing targets needs `refresh=True`), and mishandles
    a list of years. → `nearest_nodes` + `allocate`, or `node_estimate`
    for WECC240.

## Environment

23. **Missing NSRDB credentials open a browser.** `weather` calls
    `webbrowser.open(SIGNUP)`; headless runs hang or fail obscurely. →
    `ls.configure()` checks first.

24. **Cache lives in site-packages by default** and `Total`/sector classes
    overwrite the global `Cache.CACHEDIR` when their own `CACHEDIR` is set.
    → set it once with `configure(cachedir=...)`.

25. **`Total.cache` keeps every fitted estimator in memory.** Sweeps over
    hundreds of counties grow without bound. → `configure(estimator_cache=
    False)` or `batch(clear_estimator_cache=True)`.

26. **Python 3.12 only** (`requires-python == 3.12.*`).

27. **`loads.dgen.SolarModel` prints** (`print(len(weather.index))`) to
    stdout, which corrupts stdout-JSON pipelines. → redirect stdout around
    that call, or avoid it (the default `DG` path does not use it).

## Precomputed WECC files

28. **Not installed by `pip install .`.** Apart from
    `wecc/county_mwh.csv` (package data, so `loads.dgen.DG` and
    `Total(dg=True)` work from any install), `loads/wecc/*.csv*` are in the
    repository but not package data: the precomputed estimates and the DG
    files (`DG(profile="dgen")` needs `county_dg.csv.gz`). → use a clone
    with `pip install -e .`; `ls.wecc_*` raise `FileNotFoundError` saying
    so.

29. **Two DG datasets.** `county_dg.csv.gz` (dGen, 369 counties, no
    year-to-year growth; `county_dg.csv` is an uncompressed copy missing
    Santa Cruz AZ) is what `wecc_estimate.csv.gz` was calibrated with;
    `county_dg_scaled.csv.gz` (all 407 counties, scaled per state and year
    to EIA small-scale solar) is what calibration validation uses. Both are positive and start at
    2018-01-01 07:00 UTC. → choose with `wecc_dg(scaled=...)` and say
    which; `wecc_estimate + wecc_dg(scaled=False)` reproduces each month's
    EIA retail allocation **[tested in `test_skill_wecc.py`]**.

30. **`node_estimate` is uncalibrated** and allocates counties to nodes by
    constant factors from one WECC240 case snapshot
    (`node_estimate_cf.csv`); its county loads are the raw `Estimator`
    output, not `wecc_estimate`. → say so, or allocate calibrated county
    loads yourself with `ls.allocate`.

## Imported data (`Normalize`)

31. **`Normalize` sums, so a missing meter is missing load.** Every row in
    an hour is added up **[tested]**: right for a fleet total, but an hour
    in which some meters didn't report comes out low rather than NaN, and
    duplicate rows are double counted. → check the number of reporting
    units per hour in the source (`source.groupby(hour)[meter].nunique()`)
    and drop duplicates before normalizing.

32. **`Normalize` expects energy per interval.** Because rows are summed,
    sub-hourly kWh per interval comes out right (15-minute kWh × `1e-3` →
    MW) **[tested]**, but sub-hourly **power** readings are summed too and
    come out N times too large (4× for 15-minute kW). → for power
    readings, divide by the readings per hour in `scales`
    (`{"kw": 1e-3 / 4}`).

33. **Meter data is net of rooftop PV.** Map AMI or feeder deliveries to
    `elec_net_MW`, not `elec_total_MW`, and compare with model net load
    (and say which DG the model used).
