"""Load aggregation module

The `loads.aggregate.Aggregator` class is used to sum data from multiple load
sources into a panel with target columns and date/time rows. The
`loads.aggregate.aggregate` function uses it to map every WECC county to its
nearest target location and sum the county loads estimated by
`loads.estimator.Estimator`.

Example
-------

To aggregate the county total loads in August 2018 to the WECC 240 nodes, do
the following

    # load the targets
    import pandas as pd
    wecc240_gis = pd.read_csv("https://github.com/eudoxys/wecc240/raw/refs/heads/main/wecc240/gis/wecc240.csv")
    locations,latlons = wecc240_gis.GEOHASH,list(zip(wecc240_gis.LAT,wecc240_gis.LON))

    # create the target aggregator
    from loads.aggregate import Aggregator
    elec_total_MW = Aggregator(locations.unique(),"2018-08-01 00:00:00+00:00","2018-08-31 23:59:59+00:00")

    # add the sources into the targets
    from fips.counties import Counties
    from geohash import nearest2
    from loads import Total
    for state,county,lat,lon,geohash in Counties(use_index="SYSTEM",selection="WECC")[["ST","COUNTY","LAT","LON","GEOHASH"]].values:
        nearest,_,_ = nearest2([lat,lon],latlons)
        target = locations[nearest]
        elec_total_MW.add(target,Total(state,county)[["elec_total_MW"]].rename({"elec_total_MW":target},axis=1))

    # show the result
    elec_total_MW

which returns 744 hourly rows with one column of 2018 total load (MW) per
target node.

Caveat
------

  - The cache assumes that the target list has not changed. If the target list
    has changed, you must use the `refresh=True` option to force
    recalculation of mappings.

Issues
------

1. The Mexico loads have no loadshape and it's not clear what the load shape
should be. See
`https://github.com/eudoxys/wecc240/raw/refs/heads/main/wecc240/Mexico` for
details.
"""

import datetime as dt
import logging

import numpy as np
import pandas as pd

from cache import Cache
from fips.counties import Counties
from geohash import nearest2
from loads.estimator import Estimator, EstimatorConfig

_logger = logging.getLogger(__file__)

class Aggregator(pd.DataFrame):
    """Load aggregator class

    The data frame has one column per target, sorted by name, and an hourly
    `timestamp` index from `start` to `end`, initialized to zero.
    """

    def __init__(self,
        targets:list[str],
        start:dt.datetime|str,
        end:dt.datetime|str,
        ):
        """Aggregator constructor

        Arguments
        ---------

          - `targets`: the list of targets columns to aggregate into 

          - `start`: the index start date/time

          - `end`: the index end date/time
        """

        # generate the time index for the aggregation
        timestamps = pd.date_range(start,end,freq="1h") 

        # create a data frame into which data will be aggregated
        data = pd.DataFrame(
            data = np.zeros((len(timestamps),len(targets))),
            index = timestamps,
            )

        # finalize the data frame structure
        data.index.name = "timestamp"
        data.columns = sorted(targets)

        super().__init__(data)

    def add(self,target,data):
        """Add data to a target column

        Arguments
        ---------

          - `target`: target column name

          - `data`: data frame with a column named `target`, whose values are
            added to the target column where its index matches
        """

        # add the new data to the data frame
        self[target] += data[target]

def aggregate(
    targets:dict[str,list[float,float]],
    dt_range:int|list[int]|pd.DatetimeIndex,
    column:str,
    refresh:bool=False,
    ) -> [pd.DataFrame, dict[str,str]]:
    """Aggregate loads

    Arguments
    ---------

      - `targets`: dict of target names and their `[latitude,longitude]`

      - `dt_range`: date range or year for which aggregates are collected

      - `column`: sector enduse column to estimate and aggregate (must end
        with `_MW`, see `loads.estimator.EstimatorConfig.enduse`)

      - `refresh`: force refresh of cached data

    Returns
    -------

      - `pandas.DataFrame`: aggregates of loads

      - `pandas.DataFrame`: mapping of county geohash (`source`) to target
        (`target`)

    Description
    -----------

    Each WECC county is mapped to its nearest target and its `column`
    estimated by `loads.estimator.Estimator` over `dt_range` is added to that
    target.
    """

    assert column.endswith("_MW"), f"{column=} is not a column to aggregate (only MW columns can be aggregated)"

    if isinstance(dt_range,int):
        dt_range = pd.date_range(
            start=f"{dt_range}-01-01 00:00:00+0000",
            end=f"{dt_range}-12-31 23:59:59+0000",
            freq="1h",
            )
    elif isinstance(dt_range,list) and np.ndarray([isinstance(x,int) for x in dt_range]).all():
        dt_list = []
        for year in dt_range:
            dt_list.append(pd.date_range(
                start=f"{year}-01-01 00:00:00+0000",
                end=f"{year}-12-31 23:59:59+0000",
                freq="1h",
                ))
    else:
        assert isinstance(dt_range,(pd.DatetimeIndex,list)), f"{dt_range=} is not a valid DatetimeIndex, year, or list of years"
        dt_range = pd.DatetimeIndex(sorted(dt_range))

    start = dt_range.min().year
    end = dt_range.max().year

    # read cache if possible/desired
    if start == end:
        mapping_cache = Cache(package="loads",version=1,path=["aggregated",start,f"mapping.csv"])
        data_cache = Cache(package="loads",version=1,path=["aggregated",start,f"{column}.csv"])
    else:
        mapping_cache = Cache(package="loads",version=1,path=["aggregated",f"{start}-{end}",f"mapping.csv"])
        data_cache = Cache(package="loads",version=1,path=["aggregated",f"{start}-{end}",f"{column}.csv"])            
    if not refresh and data_cache.download() and mapping_cache.download():

        # read mapping
        try:
            mapping = pd.read_csv(mapping_cache.pathname,index_col=0)
            _logger.debug(f"{mapping_cache=} ok")
        except Exception as err:
            _logger.error(f"{mapping_cache=} {err}")
            mapping = None

        # read load
        try:
            data = pd.read_csv(data_cache.pathname,index_col="timestamp",parse_dates=["timestamp"])
            _logger.debug(f"{data_cache=} ok")
        except Exception as err:
            _logger.error(f"{data_cache=} {err}")
            data = None

    else:

        _logger.debug(f"cache (re)generation required")
        data = None
        mapping = None

    # if elec_total_MW is None or elec_dg_MW is None or mapping is None:
    if data is None or mapping is None or refresh:

        # build mapping table
        mapping = {}

        # get load aggregator
        data = Aggregator(targets.keys(),f"{start}-01-01 00:00:00+00:00",f"{end}-12-31 23:59:59+00:00")

        # map counties to targets
        for state,county,lat,lon,geohash in Counties(use_index="SYSTEM",selection="WECC")[["ST","COUNTY","LAT","LON","GEOHASH"]].values:

            # find nearest target
            ndx,latlon,dist = nearest2([lat,lon],targets.values())
            target = list(targets.keys())[ndx]
            _logger.info(f"mapping {county} {state} ({geohash}) to {target} ({dist=:.1f} km)")

            # save mapping
            mapping[geohash] = target

            # read county totals
            total = Estimator(f"{county} {state}",sorted(set(dt_range.year)),
                config=EstimatorConfig(enduse=column),
                ).reindex(dt_range).fillna(0)
            assert column in total.columns, f"{column=} is not found in estimate for {state=} {county=}"

            # add county load to aggregated load
            data.add(target,pd.DataFrame(
                data={target:total[column]},
                index=total.index,
                ))

        # save load results
        data.sort_index(inplace=True)
        data.round(3).to_csv(data_cache.pathname,index=True,header=True)

        # save mapping result
        mapping = pd.DataFrame(data={"target":mapping.values()},index=mapping.keys())
        mapping.index.name = "source"
        mapping.sort_index(inplace=True)
        mapping.to_csv(mapping_cache.pathname,index=True,header=True)

    return data[sorted(data.columns)],mapping

if __name__ == "__main__":
    """Create aggregate loads for WECC 240 network

    Syntax: python3 aggregate.py [--debug] [--refresh] COLUMN [START END]
    """
    import os
    import sys
    import pytz
    import matplotlib.pyplot as plt

    refresh = "--refresh" in sys.argv
    debug = "--debug" in sys.argv

    pd.options.display.max_columns = None
    pd.options.display.width = None
    # pd.options.display.max_rows = None

    if len(sys.argv) == 1:
        print("Syntax: python3 aggregate.py [--debug] [--refresh] COLUMN [START END]",file=sys.stderr)

    column = None
    start = None
    end = None
    args = [x for x in sys.argv[1:] if not x.startswith("-")]
    try:
        column = args[0]
        start = args[1]
        end = args[2]
    except:
        if column is None:
            column = "elec_total_MW"
        if start is None:
            start = "2018-01-01 00:00:00+0000"
        if end is None:
            end = "2022-12-31 23:59:59+0000"
    dt_range = pd.date_range(start=start,end=end,freq="1h")

    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)

    # read GIS data
    wecc240_gis = pd.read_csv("https://github.com/eudoxys/wecc240/raw/refs/heads/main/wecc240/gis/wecc240.csv")

    # get omitted nodes
    canada = set(wecc240_gis[wecc240_gis.LAT>49].GEOHASH.values)
    mexico = set(wecc240_gis.set_index("GEOHASH").loc[["9mtzm4"]].index.values)
    omitted = canada|mexico

    # generation target node data
    locations,latlon = list(wecc240_gis.GEOHASH),list(zip(wecc240_gis.LAT,wecc240_gis.LON))
    targets = {x:latlon[locations.index(x)] for x in set(locations) if x not in omitted}

    # read US nodes
    result = aggregate(targets,dt_range,column,refresh=refresh)[0]

    # read non-US nodes
    sources = {
        "c2c10y": "https://github.com/eudoxys/wecc240/raw/refs/heads/main/wecc240/Canada/c2c10y.csv",
        "c2u6xt": "https://github.com/eudoxys/wecc240/raw/refs/heads/main/wecc240/Canada/c2u6xt.csv",
        "9mtzm4": "https://github.com/eudoxys/wecc240/raw/refs/heads/main/wecc240/Mexico/9mtzm4.csv",

    }
    for node in omitted:
        file = sources[node]
        try:
            data = pd.read_csv(file,
                index_col=["timestamp"],
                usecols=["timestamp","load_MW"],
                parse_dates=["timestamp"],
                ).sort_index().ffill().bfill().fillna(0)
            data.columns=[node]
        except Exception as err:
            _logger.exception(f"{file} read failed ({err})")
        result = pd.merge(result,data,left_index=True,right_index=True)

    # calculate results
    total = result.ffill().bfill().sum(axis=1)/1000
    result[sorted(result.columns)].to_csv(f"tests/wecc240_2025_load.csv",index=True)

    # show results
    print(f"WECC",column,start,"--",end)
    print("       US energy    US peak                      ")
    print("Year     (TWh)        (GW)          Peak day     ")
    print("----   ---------   ---------   ------------------")
    for year in total.index.year.unique():
        data = total[total.index.year==year].to_frame()
        data.columns = [column]
        energy = data[column].sum().sum()/1e3
        peak = data.max().values[0]
        peak_dt = data[data[column]==peak].index.values[0].astype(dt.datetime)
        print(f"{year}   {energy:9.1f}   {peak:9.1f}   {peak_dt:%m/%d/%y %H:%M UTC}")

