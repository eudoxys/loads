Load Testing
------------

To run tests do the following

	python3 -m venv .venv
	. .venv/bin/activate
	python3 -m pip install --upgrade pip
	pip install -r requirements.txt pytest
	pytest test_*.py

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
read it from the cache. The weight search itself takes several minutes.
Set `LOADS_CACHEDIR` to use a cache folder other than the default. Reports
are written to the gitignored `loads/tests/calibrate/` folder.

	pytest -s test_calibrate.py
