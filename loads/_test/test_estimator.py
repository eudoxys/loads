"""Estimator tests

These tests check row counts and holdout labels, which don't depend on which
load sectors are modeled, so they use the residential sector only. This
avoids downloading the national commercial floor-area, industrial, and
agricultural inventories, which dominate the cost of a run on an empty cache.

The holdout fold tests are fast unit tests of `_get_holdout` on a synthetic
hourly index. The remaining tests build a full estimate and are marked
`network`.
"""

import numpy as np
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

# --- sampling (offline: one synthetic January, real TSGAM fit) ---

def _january(year=2018):
	index = pd.date_range(f"{year}-01-01",f"{year}-02-01",freq="h",tz="UTC",inclusive="left",name="timestamp")
	hours = np.arange(len(index))
	rng = np.random.default_rng(year)
	temperature = 50 + 10*np.sin(2*np.pi*(hours-15)/24) + rng.normal(0,1,len(index))
	humidity = 60 + 10*np.cos(2*np.pi*hours/24) + rng.normal(0,3,len(index))
	return pd.DataFrame({"temperature_degF":temperature,"humidity_pc":humidity},index=index)

@pytest.fixture
def offline(monkeypatch):
	import loads.estimator as module
	def weather(state,county,year):
		return _january(year)
	def sectors(cls,sectors,state,county,enduse):
		x = _january()
		return pd.DataFrame({enduse:300 + 2*(x["temperature_degF"]-50)},index=x.index)
	monkeypatch.setattr(module,"Weather",weather)
	monkeypatch.setattr(Estimator,"_load_sectors",classmethod(sectors))

SAMPLE = dict(sectors=["residential"],keep_actuals=False,harmonics=(0,0,2),ar=2)

def test_sampling_modes(offline):
	pred = Estimator("Alameda CA",[2018],config=EstimatorConfig(**SAMPLE))
	one = Estimator("Alameda CA",[2018],config=EstimatorConfig(**SAMPLE,samples=1))
	assert list(one.columns) == list(pred.columns)
	valid = pred["elec_total_MW"].notna()
	assert (one["elec_total_MW"][valid] > 0).all()
	assert not np.allclose(one["elec_total_MW"][valid],pred["elec_total_MW"][valid])

	every = Estimator("Alameda CA",[2018],config=EstimatorConfig(**SAMPLE,samples=20,percentile=None))
	columns = [f"sample_{n}" for n in range(20)]
	assert list(every.columns) == ["temperature_degF","humidity_pc"] + columns
	assert np.allclose(every.loc[valid,"sample_0"],one.loc[valid,"elec_total_MW"]) # same seed, same first path

	p95 = Estimator("Alameda CA",[2018],config=EstimatorConfig(**SAMPLE,samples=20,percentile=95))
	assert np.allclose(p95.loc[valid,"elec_total_MW"],np.percentile(every.loc[valid,columns],95,axis=1))
	assert (p95.loc[valid,"elec_total_MW"] >= every.loc[valid,columns].median(axis=1)).all()

def test_sampling_seed(offline):
	a = Estimator("Alameda CA",[2018],config=EstimatorConfig(**SAMPLE,samples=1))
	b = Estimator("Alameda CA",[2018],config=EstimatorConfig(**SAMPLE,samples=1))
	c = Estimator("Alameda CA",[2018],config=EstimatorConfig(**SAMPLE,samples=1,random_state=7))
	pd.testing.assert_frame_equal(a,b)
	valid = a["elec_total_MW"].notna()
	assert not np.allclose(a.loc[valid,"elec_total_MW"],c.loc[valid,"elec_total_MW"])

def test_sampling_keeps_actuals(offline):
	config = EstimatorConfig(**{**SAMPLE,"keep_actuals":True},samples=3,percentile=None)
	df = Estimator("Alameda CA",[2018],config=config)
	actual = 300 + 2*(_january()["temperature_degF"]-50)
	for column in ["sample_0","sample_1","sample_2"]:
		assert np.allclose(df[column],actual)

@pytest.mark.parametrize("samples",[-1,1.5,True,"10"])
def test_sampling_invalid_samples(offline,samples):
	with pytest.raises(EstimatorError,match="samples"):
		Estimator("Alameda CA",[2018],config=EstimatorConfig(**SAMPLE,samples=samples))

def test_sampling_invalid_percentile(offline):
	with pytest.raises(EstimatorError,match="percentile"):
		Estimator("Alameda CA",[2018],config=EstimatorConfig(**SAMPLE,samples=10,percentile=101))

def test_sampling_needs_years(offline):
	with pytest.raises(EstimatorError,match="years"):
		Estimator("Alameda CA",None,config=EstimatorConfig(**SAMPLE,samples=10))

def test_ar_default(offline):
	assert EstimatorConfig().ar is True
	config = Estimator._estimator_config(EstimatorConfig())
	assert config.ar_config is not None and list(config.ar_config.lags) == [1,2,3,4]
	assert list(Estimator._estimator_config(EstimatorConfig(ar=3)).ar_config.lags) == [1,2,3]
	assert Estimator._estimator_config(EstimatorConfig(ar=False)).ar_config is None
	settings = {x:y for x,y in SAMPLE.items() if x != "ar"} # default ar
	df = Estimator("Alameda CA",[2018],config=EstimatorConfig(**settings,samples=1))
	assert df["elec_total_MW"].notna().sum() > 700
