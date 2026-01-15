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

    # add the sources into the target
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
"""

import datetime as dt

import numpy as np
import pandas as pd

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
        data.columns = targets
        super().__init__(data)

    def add(self,target,data):
        """Add data to a target column

        Arguments
        ---------

          - `target`: target column name

          - `data`: data values to add
        """
        self[target] += data

if __name__ == "__main__":

    from loads.cast import WEATHER_FIELDS, ELEC_FIELDS, NONELEC_FIELDS
    from geohash import nearest2
    from cache import Cache

    from loads.total import Total
    from fips.counties import Counties

    pd.options.display.width = None
    pd.options.display.max_columns = None

    wecc240_gis = pd.read_csv("wecc_gis.csv")

    locations,latlon = wecc240_gis.GEOHASH,list(zip(wecc240_gis.LAT,wecc240_gis.LON))
    target_list = sorted(locations.unique())
    print(f"{len(target_list)} targets found")
    mapping = {}
    elec_total_MW = Aggregator(target_list,"2018-08-01 00:00:00+00:00","2018-08-31 23:59:59+00:00")
    elec_dg_MW = Aggregator(target_list,"2018-08-01 00:00:00+00:00","2018-08-31 23:59:59+00:00")
    for state,county,lat,lon,geohash in Counties(use_index="SYSTEM",selection="WECC")[["ST","COUNTY","LAT","LON","GEOHASH"]].values:
        nearest,_,dist = nearest2([lat,lon],latlon)
        target = locations[nearest]
        print(f"Mapping {county} {state} ({geohash}) to {target} ({dist=:.1f} km)",end="...",flush=True)
        mapping[geohash] = target
        total = Total(state,county,2018) 
        elec_total_MW.add(target,total.elec_total_MW)
        elec_dg_MW.add(target,total.elec_dg_MW)
        print("ok")

    mapping = pd.DataFrame(data={"target":mapping.values()},index=mapping.keys())
    mapping.index.name = "source"
    cache = Cache(package="loads",version=0,path=["geodata","mapping.csv"])
    mapping.sort_index().to_csv(cache.pathname,index=True,header=True)

    cache = Cache(package="loads",version=0,path=["geodata","elec_total_MW.csv"])
    elec_total_MW.round(3).to_csv(cache.pathname,index=True,header=True)

    cache = Cache(package="loads",version=0,path=["geodata","elec_dg_MW.csv"])
    elec_dg_MW.round(3).to_csv(cache.pathname,index=True,header=True)
