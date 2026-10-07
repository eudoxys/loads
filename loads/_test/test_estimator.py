"""Estimator tests"""

from loads.estimator import Estimator

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
