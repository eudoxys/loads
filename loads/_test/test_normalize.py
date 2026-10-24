"""Test `loads.normalize` module"""

import os
import pytest
import pandas as pd
import numpy as np
from loads.normalize import Normalize

TEST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),"ami.csv.gz")
TIMESTAMPS={
	"date":pd.DatetimeIndex,
	"hour":lambda x: pd.TimedeltaIndex((np.array(x)-1)*3600e9),
	"tz_offset":lambda x: pd.TimedeltaIndex(np.array(x)*3600e9),
	}
MAPPING={"elec_net_MW":"kwh_delta"}
SCALES={"kwh_delta": 1e-3}
WEATHER="Orange CA"

ami = pd.read_csv(TEST_FILE)
testargs = {
	"source":ami,
	"timestamps":TIMESTAMPS,
	"mapping":MAPPING,
	"scales":SCALES,
	}

def test_source():

	# test df source (all meters summed each hour)
	assert Normalize(**testargs).iloc[[0,-1]]["elec_net_MW"].round(6).values.tolist() == [21.717094,20.54392]

	# test str source
	nodf = {x:y if x != "source" else TEST_FILE for x,y in testargs.items()}
	assert Normalize(**nodf).iloc[[0,-1]]["elec_net_MW"].round(6).values.tolist() == [21.717094,20.54392]

def test_groups_sum_to_total():
	total = Normalize(**testargs)["elec_net_MW"]
	meters = Normalize(**testargs,groups={"kwh_delta":"meter_id"})["elec_net_MW"]
	assert np.allclose(meters.groupby(level="timestamp").sum(),total)

def test_subhourly_energy_is_summed():
	t = pd.date_range("2020-01-01",periods=8,freq="15min")
	source = pd.DataFrame({"t":list(t)*2,"m":["a"]*8+["b"]*8,"kwh":[1.0]*8+[3.0]*8})
	args = {"timestamps":{"t":pd.DatetimeIndex},"mapping":{"elec_total_MW":"kwh"},"scales":{"kwh":1e-3}}
	assert np.allclose(Normalize(source,**args)["elec_total_MW"],0.016) # 16 kWh/h
	assert np.allclose(Normalize(source,groups={"kwh":"m"},**args).xs("a")["elec_total_MW"],0.004)

def test_strgroup():
	assert Normalize(**testargs,groups={"kwh_delta":"meter_id"}).iloc[[0,-1]]["elec_net_MW"].round(6).values.tolist() == [0.00631, 0.0053]

def test_list1group():
	print(Normalize(**testargs,groups={"kwh_delta":"meter_id"}).iloc[[0,-1]]["elec_net_MW"].round(6).values.tolist())

@pytest.mark.network # merges NSRDB weather
def test_nogroups():
	for groups in [
		None,
		{"kwh_delta": "meter_id",},
		{"kwh_delta": ["circuit_id"]},
		{"kwh_delta": ["circuit_id","meter_id"]},
		]:
		df = Normalize(ami,
			timestamps={
				"date":pd.DatetimeIndex,
				"hour":lambda x: pd.TimedeltaIndex((np.array(x)-1)*3600e9),
				"tz_offset":lambda x: pd.TimedeltaIndex(np.array(x)*3600e9),
				},
			# timezone="US/Pacific",
			mapping={
				"elec_net_MW":"kwh_delta"
			},
			scales={
				"kwh_delta": 1e-3,
			},
			groups=groups,
			weather="Orange CA"
			)
		print(df,flush=True)
