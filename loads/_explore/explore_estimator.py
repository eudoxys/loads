"""
Perform sweep tests of estimator on key WECC counties and searches for most
parsimonious set of harmonics that satisfies the `TOLERANCE` threshold given
a set of possible holdout tests.

The sweep cases are independent, so they are run in parallel on all available
CPUs. Use `--jobs N` to limit the number of worker processes (`--jobs 1` runs
serially). Results are appended to `SWEEP_FILE` as each case completes, so an
interrupted run resumes where it left off.

Caveat: `etime` is wall-clock time per fit measured inside each worker, so it
will be somewhat higher than in a serial run when all cores are busy.
"""

VERSION = None
"""Result version (allows comparison with older results)"""

TOLERANCE = 0.02
"""Fractional tolerance for parsimonious harmonic search"""

SWEEP_FILE = "explore_estimator.csv" if VERSION is None else f"explore_estimator_v{VERSION}.csv"
"""File in which sweep results are stored"""

BEST_FILE = "explore_estimator_clusters.csv" if VERSION is None else f"explore_estimator_clusters_v{VERSION}.csv"
"""File in which sweep results are stored"""

CLUSTER_DATA = "../clusters.csv"
"""File in which to read clusters"""

HOLDOUT_TESTS = ["4w","5w","5d"]
"""Range of holdout tests"""

INDEX_NAMES = ["county","yearly","weekly","daily","holdout"]
"""Names of index columns"""

COLUMN_NAMES = ["mae","rmse","mape","r2","etime"]
"""Names of data columns"""

MAX_HARMONICS = {
	"daily": 13, # Nyquist limit is 12 for hourly data
	"weekly": 5, # Nyquist limit is 84 for hourly data
	"yearly": 5, # Nyquist limit is 4380 for hourly data (4392 in leap years)
}
"""Maximum harmonics to sweep"""

# python modules
import os
import sys
import argparse
from time import time
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp

# limit each worker to one BLAS/OpenMP thread so N workers don't oversubscribe
# N cores (must be set before numpy is imported; spawned workers inherit it)
for _var in ["OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS",
		"VECLIB_MAXIMUM_THREADS","NUMEXPR_NUM_THREADS"]:
	os.environ.setdefault(_var,"1")

# third-party modules
import pandas as pd
import numpy as np

# eudoxys modules
from loads.estimator import Estimator, EstimatorConfig

pd.options.display.width = None

def get_mae(df):
	"""Calculate the mean absolute error"""
	return np.mean(np.abs( df.actual - df.prediction ))

def get_rmse(df):
	"""Calculate the holdout root mean squared error"""
	return np.sqrt(np.mean(( df.actual - df.prediction )**2))

def get_mape(df):
	"""Calculate mean absolute percent error"""
	return np.mean(np.abs((df.prediction - df.actual) / (df.actual + 1e-6))) * 100

def get_r2(df):
	"""Calculate r-squared"""
	ss_res = np.sum((df.actual - df.prediction) ** 2)
	ss_tot = np.sum((df.actual - np.mean(df.actual)) ** 2)
	return 1 - (ss_res / ss_tot)

def _cpu_count():
	"""@private Number of CPUs this process may use"""
	try:
		return len(os.sched_getaffinity(0)) # honors taskset/cgroup limits (Linux)
	except AttributeError:
		return os.cpu_count() or 1 # macOS/Windows

def _warm_cache(county_st):
	"""@private Build the cached inputs for a county before any worker needs them

	Several caches are shared between counties (industry, agriculture, state
	housing units, floor area), so concurrent workers starting from a cold
	cache would race to write the same files. Running one default fit per
	county serially first populates everything the sweep reads.
	"""
	Estimator(county_st,config=EstimatorConfig())

def _run_case(ndx):
	"""@private Run one sweep case in a worker process and return its record"""
	county,yearly,weekly,daily,holdout = ndx

	# make estimator configuration to test
	config = EstimatorConfig(
		harmonics=(yearly,weekly,daily),
		holdout=holdout,
		)

	# run estimator and time it
	tic = time()
	df = Estimator(county,config=config)
	toc = time()

	# get the holdout test result
	estimate = df[df.status=="H"]

	# extract performance metrics
	return ndx, {
		"mae": float(round(get_mae(estimate),3)),
		"rmse": float(round(get_rmse(estimate),3)),
		"mape": float(round(get_mape(estimate),3)),
		"r2": float(round(get_r2(estimate),3)),
		"etime": float(round(toc-tic,3)),
		}

def _load_results():
	"""@private Load previous sweep results, if any"""
	try:
		return pd.read_csv(SWEEP_FILE,index_col=[0,1,2,3,4])
	except FileNotFoundError:
		results = pd.DataFrame(columns=COLUMN_NAMES)
		results.index = pd.MultiIndex.from_tuples([],names=INDEX_NAMES)
		return results

def _save_record(ndx,record):
	"""@private Append one record to the sweep file (main process only)"""
	df = pd.DataFrame([dict(zip(INDEX_NAMES,ndx))|record]).set_index(INDEX_NAMES)
	exists = os.path.exists(SWEEP_FILE) and os.path.getsize(SWEEP_FILE) > 0
	df.to_csv(SWEEP_FILE,mode="a" if exists else "w",index=True,header=not exists)

def main(jobs=None):
	"""Run the sweep in parallel and find the parsimonious harmonics"""

	jobs = jobs or _cpu_count()
	counties = sorted(pd.read_csv(CLUSTER_DATA).medoid.unique())

	# list sweep cases not already done
	results = _load_results()
	done = set(results.index)
	pending = [
		(county,yearly,weekly,daily,holdout)
		for county in counties
		for yearly in range(2,MAX_HARMONICS["yearly"])
		for weekly in range(2,MAX_HARMONICS["weekly"])
		for daily in range(2,MAX_HARMONICS["daily"])
		for holdout in HOLDOUT_TESTS
		if (county,yearly,weekly,daily,holdout) not in done
		]
	print(f"{len(done)} cases done, {len(pending)} pending, {jobs} workers",flush=True)

	if pending:

		# populate shared caches serially before fanning out
		for county in sorted({x[0] for x in pending}):
			print(f"  warming cache for {county}",flush=True)
			_warm_cache(county)

		# run the sweep; only this process writes the sweep file
		failed = 0
		with ProcessPoolExecutor(
				max_workers=jobs,
				mp_context=mp.get_context("spawn"), # same behavior on Linux and macOS
				max_tasks_per_child=100, # recycle workers to bound solver memory growth
				) as pool:
			futures = {pool.submit(_run_case,ndx):ndx for ndx in pending}
			for n,future in enumerate(as_completed(futures),1):
				ndx = futures[future]
				try:
					ndx,record = future.result()
				except Exception as err: # pylint: disable=broad-exception-caught
					failed += 1
					print(f"  [{n}/{len(pending)}] FAILED",*ndx,f"({type(err).__name__}: {err})",
						file=sys.stderr,flush=True)
					continue
				_save_record(ndx,record)
				print(f"  [{n}/{len(pending)}]",*ndx,flush=True)

		if failed:
			print(f"{failed} cases failed; rerun to retry them",file=sys.stderr,flush=True)
		results = _load_results()

	# find parsimonious harmonics
	result = []
	data = results.reset_index().set_index(INDEX_NAMES[0])
	for county in counties:

		_df = data.loc[[county]].sort_values(INDEX_NAMES[1:])
		_best = {}

		# scan the metrics
		for _metric in COLUMN_NAMES[:3]:

			# find the best performance for each metric
			_min = _df[_metric].min()

			# calculate the cutoff value
			_cutoff = _min * (1+TOLERANCE)

			# select the best cutoff result
			_selected = _df[_df[_metric]<=_cutoff][INDEX_NAMES[1:]+[_metric]].sort_values(["daily","weekly","yearly","holdout"])

			# save the result
			_best[_metric] = list(_selected.values[0])
			_best[_metric].append(round(_cutoff,3))
			_best[_metric].append(_min)

		# assemble the next dataframe record
		_result = pd.DataFrame(data=_best,index=INDEX_NAMES[1:]+["value","cutoff","min"]).T
		_result.index.name = "metric"
		_result.reset_index(inplace=True)
		_result[INDEX_NAMES[0]] = county

		# save it
		result.append(_result)

	# save the final results
	result = pd.concat(result).set_index(["metric",INDEX_NAMES[0]]).sort_index()
	result.to_csv(BEST_FILE,index=True,header=True)

if __name__ == "__main__":

	parser = argparse.ArgumentParser(description=__doc__.strip().split("\n\n",maxsplit=1)[0])
	parser.add_argument("-j","--jobs",type=int,default=None,
		help=f"number of worker processes (default all CPUs: {_cpu_count()})")
	main(**vars(parser.parse_args()))
