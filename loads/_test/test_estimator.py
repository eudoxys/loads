"""Estimator tests"""

import pandas as pd
import pytest

from loads.estimator import Estimator, EstimatorConfig, EstimatorError, _get_holdout

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

def test_holdout():

	df = Estimator("Alameda CA",None)
	assert len(df) == 8760
	assert "status" in df.columns
	assert "H" in df["status"].unique()

def test_reference_year():

	df = Estimator("Alameda CA",[2018])
	assert len(df) == 8760

def test_contiguous_years():
	df = Estimator("Alameda CA",[2019,2020])
	assert len(df) == 8760 + 8784

def test_split_years():
	df = Estimator("Alameda CA",[2019,2021])
	assert len(df) == 8760 + 8760

def test_all_folds():
	df = Estimator("Alameda CA",None,config=EstimatorConfig(holdout="3m",fold=True))
	assert len(df) == 8760
	assert "fold" in df.columns
	assert set(df["fold"].dropna().unique()) == {0,1,2}
	assert list(df.attrs["folds"].index) == [0,1,2,"mean"]
	assert set(df.attrs["folds"].columns) == {"MAE","RMSE","MAPE"}
