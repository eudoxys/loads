"""
Perform sweep tests of estimator on key WECC counties and searches for most
parsimonious set of harmonics that satisfies the `TOLERANCE` threshold given
a set of possible holdout tests.
"""

TOLERANCE = 0.05
"""Fractional tolerance for parsimonious harmonic search"""

SWEEP_FILE = f"explore_estimator.csv"
"""File in which sweep results are stored"""

BEST_FILE = f"explore_estimator_clusters.csv"
"""File in which sweep results are stored"""

CLUSTER_DATA = "../clusters.csv"
"""File in which to read clusters"""

HOLDOUT_TESTS = ["3m","4m","4w","5w","5d"]
"""Range of holdout tests"""

INDEX_NAMES = ["county","yearly","weekly","daily","holdout"]
"""Names of index columns"""

COLUMN_NAMES = ["mae","rmse","mape","r2","etime"]
"""Names of data columns"""

MAX_HARMONICS = {
	"daily": 8,
	"weekly": 8,
	"yearly": 8,
}
"""Maximum harmonics to sweep"""

# python modules
from time import time

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

# explore medoid counties
result = []
try:
	results = pd.read_csv(SWEEP_FILE,index_col=[0,1,2,3,4])
except:
	results = pd.DataFrame(columns=COLUMN_NAMES)
	results.index = [[]]*len(INDEX_NAMES)
	results.index.names = INDEX_NAMES

# sweep cluster medoid counties
for county in sorted(pd.read_csv(CLUSTER_DATA).medoid.unique()):

	# sweep yearly harmonics
	for yearly in range(2,MAX_HARMONICS["yearly"]):

		# sweep weekly harmonics
		for weekly in range(2,MAX_HARMONICS["weekly"]):

			# sweep daily harmonics
			for daily in range(2,MAX_HARMONICS["daily"]):

				# sweep holdout tests
				for holdout in HOLDOUT_TESTS:

					# make index
					ndx = (county,yearly,weekly,daily,holdout)
					if ndx in results.index:
						continue # skip if already done
					print(" ",*ndx,flush=True)

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
					mae = [float(round(get_mae(estimate),3))]
					rmse = [float(round(get_rmse(estimate),3))]
					mape = [float(round(get_mape(estimate),3))]
					r2 = [float(round(get_r2(estimate),3))]
					etime = [float(round(toc-tic,3))]

					# make the new data record
					data = {x:globals()[x] for x in INDEX_NAMES+COLUMN_NAMES}
					df = pd.DataFrame(data=data)
					df.set_index(INDEX_NAMES,inplace=True)

					# add it to the results and save progress
					results = pd.concat([results,df])
					results.to_csv(SWEEP_FILE,index=True,header=True)

	# find parsimonious harmonics
	data = results.reset_index().set_index(INDEX_NAMES[0])
	_df = data.loc[county].sort_values(INDEX_NAMES[1:])
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
	_result.set_index([INDEX_NAMES[0],"metric"])

	# save it
	result.append(_result)

# save the final results
result = pd.concat(result).set_index(["metric",INDEX_NAMES[0]]).sort_index()
result.to_csv(BEST_FILE,index=True,header=True)
