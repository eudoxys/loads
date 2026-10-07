"""Perform sweep tests of estimator on key WECC counties
and search for most parsimonious set of harmonics that
satisfies the `TOLERANCE` threshold.
"""

TOLERANCE = 0.05
"""Fractional tolerance for parsimonious harmonic search"""

SWEEP_FILE = "explore_estimator.csv"
"""File in which sweep results are stored"""

# python modules
from time import time

# third-party modules
import pandas as pd
import numpy as np

# eudoxys modules
from loads.estimator import Estimator, EstimatorConfig

pd.options.display.width = None

def mae(df):
	"""Calculate the mean absolute error"""
	return np.mean(np.abs( df.actual - df.prediction ))

def rmse(df):
	"""Calculate the holdout root mean squared error"""
	return np.sqrt(np.mean(( df.actual - df.prediction )**2))

def mape(df):
	"""Calculate mean absolute percent error"""
	return np.mean(np.abs((df.prediction - df.actual) / (df.actual + 1e-6))) * 100

def r2(df):
	"""Calculate r-squared"""
	ss_res = np.sum((df.actual - df.prediction) ** 2)
	ss_tot = np.sum((df.actual - np.mean(df.actual)) ** 2)
	return 1 - (ss_res / ss_tot)

# explore medoid counties
result = []
results = pd.read_csv(SWEEP_FILE,index_col=[0,1,2,3])
for county in sorted(pd.read_csv("../clusters.csv").medoid.unique()):
	for yearly in range(2,8):
		for weekly in range(2,7):
			for daily in range(2,13):
				ndx = (county,yearly,weekly,daily)
				if ndx in results.index:
					continue
				print(*ndx,"...",flush=True)
				config = EstimatorConfig(harmonics=(yearly,weekly,daily))
				tic = time()
				df = Estimator(county,config=config)
				toc = time()
				holdout = df[df.status=="H"]
				data = {
					"county": county,
					"yearly": yearly,
					"weekly": weekly,
					"daily": daily,
					"mae":[float(round(mae(holdout),3))],
					"rmse":[float(round(rmse(holdout),3))],
					"mape":[float(round(mape(holdout),3))],
					"r2":[float(round(r2(holdout),3))],
					"time":[float(round(toc-tic,3))],
					}
				df = pd.DataFrame(data=data)
				df.set_index(["county","yearly","weekly","daily"],inplace=True)
				results = pd.concat([results,df])
				results.to_csv(SWEEP_FILE,index=True,header=True)

	# find parsimonious harmonics
	data = results.reset_index().set_index("county")
	_df = data.loc[county].sort_values(["yearly","weekly","daily"])
	_best = {}
	for _metric in ["mae","rmse","mape"]:
	    _min = _df[_metric].min()
	    _cutoff = _min * (1+TOLERANCE)
	    _selected = _df[_df[_metric]<=_cutoff][["yearly","weekly","daily",_metric]].sort_values(["daily","weekly","yearly"])
	    _best[_metric] = list(_selected.values[0])
	    _best[_metric].append(_cutoff.round(3))
	    _best[_metric].append(_min)
	_result = pd.DataFrame(data=_best,index=["yearly","weekly","daily","value","cutoff","min"]).T
	_result.index.name = "metric"
	_result.reset_index(inplace=True)
	_result["county"] = county
	_result.set_index(["county","metric"])
	result.append(_result)

result = pd.concat(result).set_index(["metric","county"]).sort_index()
result.to_csv("explore_estimator_clusters.csv",index=True,header=True)