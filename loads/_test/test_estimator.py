"""Estimator tests

These tests check row counts and holdout labels, which don't depend on which
load sectors are modeled, so they use the residential sector only. This
avoids downloading the national commercial floor-area, industrial, and
agricultural inventories, which dominate the cost of a run on an empty cache.

The holdout fold tests are fast unit tests of `_get_holdout` on a synthetic
hourly index. The remaining tests build a full estimate and are marked
`network`.
"""

import pandas as pd
import pytest

from loads.estimator import Estimator, EstimatorConfig, EstimatorError, _get_holdout

CONFIG = EstimatorConfig(sectors=["residential"])

def _hours(year=2018):
	index = pd.date_range(f"{year}-01-01",f"{year+1}-01-01",freq="h",tz="UTC",inclusive="left")
	return pd.DataFrame({"x":1.0},index=index)

def test_fold_default_matches_original():
	df = _hours()
	ndx = df.index.day_of_year
	expected = df.index[ndx % 5 == 4]
	assert _get_holdout(df,"5d").equals(expected)
	assert _get_holdout(df,"5d",0).equals(expected)

@pytest.mark.parametrize("freq",["6h","5d","4w","3m"])
def test_folds_partition(freq):
	df = _hours()
	count = int(freq[:-1])
	holdouts = [_get_holdout(df,freq,k) for k in range(count)]
	assert sum(len(h) for h in holdouts) == len(df)
	assert pd.Index(sorted(set().union(*[set(h) for h in holdouts]))).equals(df.index)

def test_fold_shift():
	df = _hours()
	ndx = df.index.day_of_year
	for k in range(5):
		assert _get_holdout(df,"5d",k).equals(df.index[(ndx - k) % 5 == 4])

@pytest.mark.parametrize("fold",[-1,5,True,1.5])
def test_fold_invalid(fold):
	with pytest.raises(EstimatorError):
		_get_holdout(_hours(),"5d",fold)

@pytest.mark.network
def test_holdout():

	df = Estimator("Alameda CA",None,config=CONFIG)
	assert len(df) == 8760
	assert "status" in df.columns
	assert "H" in df["status"].unique()

@pytest.mark.network
def test_reference_year():

	df = Estimator("Alameda CA",[2018],config=CONFIG)
	assert len(df) == 8760

@pytest.mark.network
def test_contiguous_years():
	df = Estimator("Alameda CA",[2019,2020],config=CONFIG)
	assert len(df) == 8760 + 8784

@pytest.mark.network
def test_split_years():
	df = Estimator("Alameda CA",[2019,2021],config=CONFIG)
	assert len(df) == 8760 + 8760

@pytest.mark.network
def test_all_folds():
	df = Estimator("Alameda CA",None,config=EstimatorConfig(sectors=["residential"],holdout="3m",fold=True))
	assert len(df) == 8760
	assert "fold" in df.columns
	assert set(df["fold"].dropna().unique()) == {0,1,2}
	assert list(df.attrs["folds"].index) == [0,1,2,"mean"]
	assert set(df.attrs["folds"].columns) == {"MAE","RMSE","MAPE"}
