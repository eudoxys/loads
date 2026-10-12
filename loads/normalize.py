"""Imported data normalization

The `loads.normalize.Normalize` class is used to normalize an arbitrary
dataframe as standard loads dataframes. To normalize a data source the
following operations are performed

1. Data is read from the source as CSV if the `source` is specified as a
   string. Remote sources URLs are permitted. See `pandas.read_csv()` for
   details. Otherwise, the source is expected to be a `pandas.DataFrame`.

2. The date/time index is constructed from the `timestamps` argument. One and
   only one column primary date/time column must be a `pandas.DatetimeIndex`
   data. Additional date/time columns must be `pandas.TimedeltaIndex` data,
   which are added to the primary date/time index. 

   Callables may be used to perform transformation if needed provided the
   return is either a `pandas.DatetimeIndex` or `pandas.TimedeltaIndex`, as
   necessary. The default timezone for the primary date/index is `"UTC"` but
   can be changed using the `timezone` argument.

   Sub-hourly data is down-sampled to hourly using the `mean()` aggregator.
   Super-hourly data cannot be up-sampled.

3. The `mapping` argument is used to indicate which standard columns are
   collected from which source columns. Note that the mapping is strictly
   one-to-one.

4. Input data is rescaled using the `scales` argument, i.e.,
   `scales={"my_column":1e-3}` to convert from kW to MW.

5. The `groups` column is used to return grouped results, e.g.,
   `{"kwh_delta": ["circuit_id","meter_id"]}` to specify the `kwh_delta` source
   columns should be grouped using the `circuit_id` and then the `meter_id`.
   All grouped data is summed.

   This results in a non-standard multi-index where the leading index columns
   are the requests groups based on the source group columns. To get a
   standard loads data frame simply use the multi-index to select the
   subgroup that results in a simple date/time indexed dataframe.

6. Weather data can be merged by specifying the county name and state code
   with the `weather` argument, e.g., `state="Alameda CA"`.

Examples
--------

The Python commands

	from loads.normalize import Normalize
	Normalize("loads/_test/ami.csv.gz",
		timestamps={
			"date":pd.DatetimeIndex,
			"hour":lambda x: pd.TimedeltaIndex((np.array(x)-1)*3600e9),
			"tz_offset":lambda x: pd.TimedeltaIndex(np.array(x)*3600e9),
			},
		mapping={
			"elec_net_MW":"kwh_delta"
		},
		scales={
			"kwh_delta": 1e-3,
		})

generates the following output

	                           elec_net_MW
	timestamp                                                                                                    
	2015-01-01 08:00:00+00:00    21.717094
	2015-01-01 09:00:00+00:00    20.995446
	2015-01-01 10:00:00+00:00    20.252573
	2015-01-01 11:00:00+00:00    19.605594
	2015-01-01 12:00:00+00:00    19.325199
	...                                ...
	2016-01-02 03:00:00+00:00    24.919207
	2016-01-02 04:00:00+00:00    24.377614
	2016-01-02 05:00:00+00:00    23.533434
	2016-01-02 06:00:00+00:00    22.303888
	2016-01-02 07:00:00+00:00    20.543920

	[8784 rows x 6 columns]
"""

from zoneinfo import ZoneInfo
from typing import Callable

import pandas as pd
import numpy as np

from weather import Weather

class Normalize(pd.DataFrame):
	"""Load data normalization implementation"""

	STANDARD_COLUMNS = [
		"elec_baseload_MW",
		"elec_heating_MW",
		"elec_cooling_MW",
		"elec_dg_MW",
		"elec_total_MW",
		"elec_net_MW",
		"nonelec_baseload_MW",
		"nonelec_heating_MW",
		"nonelec_total_MW",
	]
	"""Standard columns to use to normalize load data"""

	DEFAULT_TIMEZONE = "UTC"
	"""The default timezone to use when the date/time index os not tz-aware"""

	DST_STRATEGY = {
		"ambiguous": "infer",
		"nonexistent": "shift_forward",
	}

	def __init__(self,
		source:str|pd.DataFrame,
		*,
		timestamps:dict[str,pd.DatetimeIndex|pd.TimedeltaIndex|Callable]=None,
		timezone:str=None,
		scales:dict[str,float]=None,
		mapping:dict[str,str]=None,
		groups:dict[str]=None,
		weather:str=None,
		):
		"""Construct a normalize data frame from source data

		Arguments
		---------
		- `source`: source of data
		- `mapping`: column mapping for standard columns (see
		  `loads.Normalize.STANDARD_COLUMNS` for allowed keys)
		- `groups`: source data grouping
		- `weather`: optional county for weather data
		"""

		if groups is None:
			groups = []

		if timezone is None:
			timezone = self.DEFAULT_TIMEZONE
		elif isinstance(timezone,str):
			timezone = ZoneInfo(timezone)

		if isinstance(source,str):
			source = pd.read_csv(source)
		assert isinstance(source,pd.DataFrame), f"{source=} must be a pandas dataframe"	

		# construct date/time index of data
		dt_index = None
		for key,value in [(x,y) for x,y in timestamps.items() if y is pd.DatetimeIndex]:
			if dt_index is None:
				dt_index = value(source[key])
			else:
				raise ValueError(f"{timestamp=} can only contain one primary datetime index")
		for key,value in [(x,y) for x,y in timestamps.items() if y is not pd.DatetimeIndex]:
			dt_index += value(source[key])
		try: # force to tz if not tz-aware
			dt_index = dt_index.tz_localize(timezone)
		except TypeError: # already tz-aware
			dt_index = dt_index.tz_convert("UTC")

		# gather mapped data
		data = []
		for key,value in mapping.items():

			# read raw data
			raw = {
				key:np.array(source[value]),
				}

			# perform scaling, if any
			if value in scales:
				raw[key] *= scales[value]

			# load grouping data
			if value in groups:
				for group in groups[value] if isinstance(groups[value],list) else [groups[value]]:
					raw[group] = source[group].values

			# construct data frame			
			df = pd.DataFrame(
				data=raw,
				index=dt_index
				).sort_index()
			df.index.name = "timestamp"
			df.reset_index(inplace=True)

			# construct grouper
			grouper = ["timestamp"]
			if value in groups:
				group = groups[value] if isinstance(groups[value],list) else [groups[value]]
				grouper = group + grouper

			# add resampled grouped data to final dataframe
			df = df.set_index(grouper).groupby(
				[pd.Grouper(level=x) for x in grouper[:-1]] +
				[pd.Grouper(level="timestamp",freq="1h")]
				).mean().reset_index()
			data.append(df.groupby(grouper).sum())

		# assemble final data frame
		data = pd.concat(data,axis=1)

		# get weather data
		if isinstance(weather,str):
			years = dt_index.year.unique()
			county,state = " ".join(weather.split()[:-1]),weather.split()[-1]
			weather = pd.concat([Weather(state,county,year) for year in years])
			data = pd.merge(
				left=data.reset_index(),
				right=weather.loc[dt_index.unique()],
				left_on="timestamp",
				right_index=True,
				).set_index(grouper)

		# initialize base class
		super().__init__(data)

if __name__ == '__main__':
	
	pd.options.display.width = None
	pd.options.display.max_columns = None

	ami = pd.read_csv("_test/ami.csv.gz")
	print(ami,flush=True)

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
