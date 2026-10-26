# Operations

Running `loads` reliably inside automated workflows: installation, data
access, credentials, caching, runtime and memory.

## Install

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install --upgrade pip && pip install git+https://github.com/eudoxys/loads
```

`loads` and its siblings install from GitHub (`eudoxys/cache`, `fips`,
`weather`, `eia`, `geohash`, and `nimish/estimator` for TSGAM). The install
includes the Python modules, this skill's markdown, and the WECC data files
the code reads (`county_mwh.csv`, the county DG files and the precomputed
WECC county and node estimates; about 126 MB). To work on `loads` itself,
or to run its tests, validation and the `Calibrate` recipe (whose data is
repository-only), use a clone:

```bash
git clone https://github.com/eudoxys/loads && cd loads
python3.12 -m venv .venv && . .venv/bin/activate
pip install --upgrade pip && pip install -e . pytest
pytest loads/_test -m "not network"     # offline tests (no network needed)
```

Install the skill for an agent by linking this folder into its skills
folder, e.g. for Claude Code:

```bash
ln -s "$PWD/loads/skill" ~/.claude/skills/loads     # or a project's .claude/skills/
```

## Data sources fetched at first use

| Source | Used by | Host |
|---|---|---|
| ResStock 2018 county end-use profiles | `RESstock` → `Residential` | `oedi-data-lake.s3.amazonaws.com` |
| ComStock 2018 county end-use profiles | `COMstock` → `Commercial` | `oedi-data-lake.s3.amazonaws.com` |
| Census housing-unit estimates | `Units` | `www2.census.gov` |
| OpenEI commercial floor area (#906) | `Floorarea` | `data.openei.org` |
| NLR county industry/agriculture (#97) | `Industry`, `Agriculture` | `data.nlr.gov` |
| NSRDB PSM4 hourly weather (via pvlib) | `weather.Weather` → every `Total` | NSRDB API (key) |
| EIA-861M sales / small-scale solar | `eia.HS861m`, `Form861m` → `loads.dgen.DG`, `Total(dg=True)` | `www.eia.gov` |
| WECC240 node GIS (optional) | your aggregation | `github.com/eudoxys/wecc240` |

Bundled (offline; `loads/_test/data`, `loads/caiso` and `loads/isone`
in a clone only): `fips` county/state metadata,
`loads/clusters.csv`, `loads/wecc/*` (the 2018–2022
WECC county and WECC240 node estimates, county DG, EIA retail allocations
and contribution factors), `loads/_test/data/*` (WECC/CAISO EIA-930 hourly
load, monthly state energy and regional peak targets, CAISO membership),
`loads/caiso`, `loads/isone` reference data.

In network-restricted sandboxes these hosts are often blocked; the
symptom is `URLError` / `403 Forbidden` from the first constructor. In
that case the precomputed WECC readers (`wecc_estimate`, `wecc_dg`,
`node_estimate`) and every `loads.skill` helper that works on frames
(`read_csv`, `validate`, `summary`, `allocate`, `shape_to_targets`, ...)
still work. Say what is blocked and ask for the files rather than
retrying.

## NSRDB credentials

`~/.nsrdb/credentials.json` containing `{"<email>": "<api_key>"}`. The
user registers at https://developer.nlr.gov/signup/. CI
(`.github/workflows/validate.yaml`) writes it from a `NSRDB_CREDENTIALS`
secret; do the same in your CI. `ls.check_credentials()` returns whether
the file is usable; `configure()` raises if not.

## Cache

`cache.Cache` stores everything under `CACHEDIR/loads/<version>/<state>/
<county>/...` (and `CACHEDIR/weather/...` etc.). Defaults to a `.cache`
folder inside the installed `cache` package. The package's tests and CI
use `$LOADS_CACHEDIR`, as does `configure()`. Set it once:

```python
ls.configure(cachedir="/data/eudoxys-cache")   # or env LOADS_CACHEDIR
```

- Cache files are CSV(.gz) keyed by state/county/source; delete a county
  folder to force a rebuild of just that county, or pass `refresh=True`.
  Exception: when `Residential` or `Commercial` finds no local
  `R.csv.gz`/`C.csv.gz`, it first downloads the county's file from the
  `cache` archive (the Eudoxys WECC data archive, github.com/eudoxys/wecc),
  so deleting the folder re-downloads those two; use `refresh=True` to
  rebuild them from ResStock/ComStock.
- `cache` has backup/restore (`cache backup -f file.tar.gz`, `cache
  restore -f file.tar.gz`) for moving a warmed cache between machines; a
  warmed cache is the practical way to run `loads` where the data hosts are
  unreachable.
- Cache writes are not atomic. Do not run two processes on the same county
  at once.

## Runtime and memory

- First call for a county: several downloads plus a TSGAM fit per target
  column (CVXPY + CLARABEL). Expect minutes. Cached reruns: seconds plus
  the fit (fitted models are cached only in memory, per process).
- `county_loads(sectors=True)` fits four models (total, residential,
  commercial, DG); without sectors, two.
- Reading `wecc_estimate` takes a few seconds even for all 407 counties
  (65 MB compressed; about 150 MB as a frame, about 400 MB peak while
  parsing).
- `Calibrate(search=True)` solves 88 (two regions) programs per month; for
  all 407 WECC counties a month takes minutes.
- Sampling cost scales with `samples`.
- A full WECC sweep (≈400 counties) takes hours. Run it in the background,
  log progress, write per-county outputs so it can resume.
- `Total.cache` holds fitted estimators; disable or clear it in sweeps.
- Parallelism: separate processes per state are safe if they share no
  county; the cache layout is per county.

## Logging

`loads` modules log via `logging.getLogger(__file__)`. For cache hits and
missing building types:

```python
import logging
logging.basicConfig(level=logging.INFO)
logging.getLogger().setLevel(logging.DEBUG)   # very chatty
```

## Versions and provenance

`loads.skill` records the installed `loads` version (and commit, for a
`git+` install) in `frame.attrs["loadskill"]["loads_version"]` and in
every `.meta.json` sidecar. Pin `loads` to a commit for reproducible
studies:

```toml
dependencies = ["loads @ git+https://github.com/eudoxys/loads@<commit>"]
```

The skill ships inside `loads`, so its documentation and helpers match the
installed version. `loads/_test/test_skill_loads_api.py` fails when `loads`
changes behavior the skill documents; it runs with the package's tests.
