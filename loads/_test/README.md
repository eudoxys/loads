Load Testing
------------

To run the tests do the following from the repository root folder

	python3 -m venv .venv
	. .venv/bin/activate
	python3 -m pip install --upgrade pip
	pip install -e . pytest
	pytest loads/_test

Weather data requires NSRDB credentials in `~/.nsrdb/credentials.json` (see
https://www.eudoxys.com/weather). The first run downloads the building,
census, and weather data needed by the tests, which can take several minutes.

Estimator tests
---------------

`test_estimator.py` checks the row counts of `loads.estimator.Estimator`
results for Alameda County CA, for the holdout test, the reference year, and
contiguous and non-contiguous target years.

	pytest test_estimator.py

Calibration test
----------------

`test_calibrate.py` calibrates August 2020 county loads for all 407 WECC
counties to the state energy and CAISO/WECC peak targets in `data/`
(`energy_target.csv`, `peak_target.csv`, `state_groups.csv`) using the
predeclared 88-point weight search of `loads.calibrate.Calibrate`.

County loads are TSGAM predictions from the local `cache` package files
(2018 training data and 2020 weather), so nothing is downloaded when the
cache is populated. The first run builds and caches the 744 x 407 load matrix
in parallel (`LOADS_TEST_WORKERS` processes, default all cores); later runs
read it from the cache. Running `python test_calibrate.py` (optionally with
`--refresh`) builds the load matrix without running the tests. The weight
search itself takes several minutes. Set `LOADS_CACHEDIR` to use a cache
folder other than the default. Reports are written to the gitignored
`loads/tests/calibrate/` folder.

Because building the inputs from an empty cache downloads data for every
WECC county and takes hours, the test is skipped (e.g., in CI) unless the
cache already holds them; set `LOADS_TEST_BUILD=1` to build them anyway.
`test_calibrate_synthetic.py` checks the formulation on a small synthetic
system in seconds and always runs.

	pytest -s test_calibrate.py
