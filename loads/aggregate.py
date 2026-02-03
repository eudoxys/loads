"""Load aggregation module

The `loads.aggregate.Aggregator` class is used to sum data from multiple load
sources into a panel with target columns and date/time rows.

Example
-------

To aggregate the county net loads in 2018 to the WECC 240 nodes, do the following

    # load the targets
    import pandas as pd
    wecc240_gis = pd.read_csv("wecc_gis.csv")
    locations,latlons = wecc240_gis.GEOHASH,list(zip(wecc240_gis.LAT,wecc240_gis.LON))

    # create the target aggregator
    from aggregate import Aggregator
    elec_net_MW = Aggregator(locations.unique(),"2018-08-01 00:00:00+00:00","2018-08-31 23:59:59+00:00")

    # add the sources into the targets
    from fips.counties import Counties
    from geohash import nearest2
    from loads import Total
    for state,county,lat,lon,geohash in Counties(use_index="SYSTEM",selection="WECC")[["ST","COUNTY","LAT","LON","GEOHASH"]].values:
        nearest,_,_ = nearest2([lat,lon],latlons)
        elec_net_MW.add(locations[nearest],Total(state,county,2018).elec_net_MW)

    # show the result
    elec_net_MW

which outputs the following

                                    9wdb95      9we1bp       9w1zzg      9w1wf0      9w3h8n  ...       9wve62      9x5w98     9r0vxp      9q9wtp     9qcf5u
    timestamp                                                                                ...                                                           
    2018-08-01 00:00:00+00:00  1621.573616  414.073611  1782.010695  262.994463  195.116403  ...  4524.774448  178.820562  18.938856  733.006805  29.857368
    2018-08-01 01:00:00+00:00  1530.552684  390.532792  1658.643979  248.203058  185.773275  ...  4223.061368  173.201746  17.857119  705.921253  28.133774
    2018-08-01 02:00:00+00:00  1458.137901  379.217986  1584.314139  224.212423  170.230022  ...  4024.300160  160.189473  15.008123  645.901691  26.311544
    2018-08-01 03:00:00+00:00  1335.935348  351.448744  1467.182127  202.378768  162.879603  ...  3739.634554  145.575807  12.877674  580.512879  23.023998
    2018-08-01 04:00:00+00:00  1184.926588  294.431022  1271.337030  178.383016  150.824905  ...  3301.198850  119.546684  11.816122  518.329300  19.926388
    ...                                ...         ...          ...         ...         ...  ...          ...         ...        ...         ...        ...
    2018-08-31 19:00:00+00:00  1534.926260  386.855379  1970.102717  210.877473  149.757533  ...  4726.463890  120.781514   7.811379  404.228875  14.377003
    2018-08-31 20:00:00+00:00  1582.044330  406.931965  2072.660856  215.731027  160.488766  ...  4596.176870  125.019204   8.673329  444.622690  14.551050
    2018-08-31 21:00:00+00:00  1585.495644  421.218430  2127.867872  218.461188  160.421810  ...  4463.478650  125.066515   9.958405  488.985919  13.789322
    2018-08-31 22:00:00+00:00  1596.007055  429.829066  2163.327877  225.021390  165.854757  ...  4250.042867  136.517815  11.951432  526.965799  15.507520
    2018-08-31 23:00:00+00:00  1642.285736  435.021499  2090.116596  231.605925  164.110512  ...  4091.273032  143.445191  13.862095  551.231402  17.259998

    [744 rows x 126 columns]

Caveat
------

  - The cache assumes that the target list has not changed. If the target list
    has changed, you must use the `refresh=True` option to force
    recalculation of mappings.
"""

import datetime as dt
import logging

import numpy as np
import pandas as pd

from cache import Cache
from fips.counties import Counties
from geohash import nearest2
from loads.total import Total

_logger = logging.getLogger(__file__)

class Aggregator(pd.DataFrame):
    """Load aggregator class

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
        timestamps = pd.date_range(start,end,freq="1h") 
        data = pd.DataFrame(
            data = np.zeros((len(timestamps),len(targets))),
            index = timestamps,
            )
        data.index.name = "timestamp"
        data.columns = sorted(targets)
        super().__init__(data)

    def add(self,target,data):
        """Add data to a target column

        Arguments
        ---------

          - `target`: target column name

          - `data`: data values to add
        """
        self[target] += data[target]

def aggregate(
    targets:dict[str,list[float,float]],
    year:int,
    column:str,
    refresh:bool=False,
    ) -> [pd.DataFrame, dict[str,str]]:
    """Aggregate net loads

    Arguments
    ---------

      - `targets`: list of targets locations

      - `year`: year for which aggregrates are collected

      - `refresh`: force refresh of cached data

    Returns
    -------

      - `pandas.DataFrame`: aggregates of net loads

      - `dict`: result of mapping to targets
    """

    assert column.endswith("_MW"), f"{column=} is not a column to aggregate (only MW columns can be aggregated)"

    # read cache if possible/desired
    mapping_cache = Cache(package="loads",version=0,path=["aggregated",year,f"mapping.csv"])
    data_cache = Cache(package="loads",version=0,path=["aggregated",year,f"{column}.csv"])
    if data_cache.exists() and mapping_cache.exists() and not refresh:

        # read mapping
        try:
            mapping = pd.read_csv(mapping_cache.pathname,index_col=0)
            _logger.debug(f"{mapping_cache=} ok")
        except Exception as err:
            _logger.error(f"{mapping_cache=} {err}")
            mapping = None

        # read net load
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
    if data is None or mapping is None:

        # build mapping table
        mapping = {}
        start = f"{year}-01-01 00:00:00+00:00"
        end = f"{year}-12-31 23:59:59+00:00"

        # get net load aggregator
        data = Aggregator(targets.keys(),start,end)

        # map counties to targets
        for state,county,lat,lon,geohash in Counties(use_index="SYSTEM",selection="WECC")[["ST","COUNTY","LAT","LON","GEOHASH"]].values:

            # find nearest target
            ndx,latlon,dist = nearest2([lat,lon],targets.values())
            target = list(targets.keys())[ndx]
            _logger.info(f"mapping {county} {state} ({geohash}) to {target} ({dist=:.1f} km)")

            # save mapping
            mapping[geohash] = target

            # read county totals
            total = Total(state,county,year)
            assert column in total.columns, f"{column=} is not found in totals for {state=} {counyt=} {year=}"

            # add county net load to aggregated load
            data.add(target,pd.DataFrame(
                data={target:total[column]},
                index=total.index,
                ))
            assert not data.isna().any().any(), f"{state} {county} {year} {geohash} --> {target} has NA values {data[data.isna()]}"

        # save net load results
        data.round(3).to_csv(data_cache.pathname,index=True,header=True)

        # save mapping result
        mapping = pd.DataFrame(data={"target":mapping.values()},index=mapping.keys())
        mapping.index.name = "source"
        mapping.sort_index(inplace=True)
        mapping.to_csv(mapping_cache.pathname,index=True,header=True)

    return data[sorted(data.columns)],mapping

if __name__ == "__main__":
    """Create aggregate loads for WECC 240 network

    Syntax: python3 aggregate.py [--debug] [--refresh] COLUMN YEAR ...
    """
    import os
    import sys
    import pytz

    pd.options.display.max_columns = None
    pd.options.display.width = None
    # pd.options.display.max_rows = None

    refresh = "--refresh" in sys.argv
    debug = "--debug" in sys.argv

    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)

    wecc240_gis = pd.read_csv("https://github.com/eudoxys/wecc240/raw/refs/heads/main/wecc240/gis/wecc240.csv")
    canada = set(wecc240_gis[wecc240_gis.LAT>49].GEOHASH.values)
    mexico = set(wecc240_gis.set_index("GEOHASH").loc[["9mtzm4"]].index.values)
    omitted = canada|mexico

    locations,latlon = list(wecc240_gis.GEOHASH),list(zip(wecc240_gis.LAT,wecc240_gis.LON))
    targets = {x:latlon[locations.index(x)] for x in set(locations) if x not in omitted}

    column = None
    try:
        column = [x for x in sys.argv[1:] if not x.startswith("-")][0]
        year = int([x for x in sys.argv[1:] if not x.startswith("-")][1])
    except:
        print("Syntax: python3 aggregate.py [--debug] [--refresh] COLUMN YEAR",file=sys.stderr)
        if column is None:
            column = "elec_net_MW"
        year = 2020

    # read US nodes
    result = aggregate(targets,year,column,refresh=refresh)[0]

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
                )
            data.columns=[node]
        except Exception as err:
            _logger.exception(f"{file} read failed ({err})")
        result = pd.merge(result,data,left_index=True,right_index=True)

    print(f"WECC {year} {column}:")
    print(f"Peak load...... {result.sum(axis=1).max()/1000:.1f} GW")
    print(f"Total energy... {aggregate(targets,year,column,refresh=refresh)[0].sum(axis=1).sum()/1e6:.1f} TWh")

    result[sorted(result.columns)].to_csv("tests/wecc240_loads_2020.csv",index=True)
