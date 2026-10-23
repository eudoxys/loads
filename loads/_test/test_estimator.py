"""Estimator tests

These tests check row counts and holdout labels, which don't depend on which
load sectors are modeled, so they use the residential sector only. This
avoids downloading the national commercial floor-area, industrial, and
agricultural inventories, which dominate the cost of a run on an empty cache.
"""

import pytest

from loads.estimator import Estimator, EstimatorConfig

pytestmark = pytest.mark.network

CONFIG = EstimatorConfig(sectors=["residential"])

def test_holdout():

	df = Estimator("Alameda CA",None,config=CONFIG)
	assert len(df) == 8760
	assert "status" in df.columns
	assert "H" in df["status"].unique()

def test_reference_year():

	df = Estimator("Alameda CA",[2018],config=CONFIG)
	assert len(df) == 8760

def test_contiguous_years():
	df = Estimator("Alameda CA",[2019,2020],config=CONFIG)
	assert len(df) == 8760 + 8784

def test_split_years():
	df = Estimator("Alameda CA",[2019,2021],config=CONFIG)
	assert len(df) == 8760 + 8760
