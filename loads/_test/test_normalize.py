"""Test `loads.normalize` module"""

import os
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

	# test df source
	assert Normalize(**testargs).iloc[[0,-1]]["elec_net_MW"].round(6).values.tolist() == [0.021523,0.020201]

	# test str source
	nodf = {x:y if x != "source" else TEST_FILE for x,y in testargs.items()}
	assert Normalize(**nodf).iloc[[0,-1]]["elec_net_MW"].round(6).values.tolist() == [0.021523,0.020201]

def test_strgroup():
	assert Normalize(**testargs,groups={"kwh_delta":"meter_id"}).iloc[[0,-1]]["elec_net_MW"].round(6).values.tolist() == [0.00631, 0.0053]

def test_list1group():
	print(Normalize(**testargs,groups={"kwh_delta":"meter_id"}).iloc[[0,-1]]["elec_net_MW"].round(6).values.tolist())

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
