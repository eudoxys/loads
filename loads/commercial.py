"""Commercial building load data accessor


The commercial load data frame collects and consolidates `COMstock` data.
Floor areas are obtained from `Floorarea` data to scale loads to actual
floor area of the county rather than the floor area in Comstock's samples.

Examples
--------

To get the commercial building load data for Alameda County CA, use the following command

    from loads import Commercial
    print(Commercial(state="CA",county="Alameda"))

which outputs the following

                               elec_baseload_MW  ...  nonelec_total_MW
    timestamp                                    ...
    2018-01-01 00:00:00+00:00         1302.4337  ...          530.8230
    2018-01-01 01:00:00+00:00         1278.7185  ...          601.4498
    2018-01-01 02:00:00+00:00         1187.3559  ...          676.6662
    2018-01-01 03:00:00+00:00         1098.1876  ...          677.1097
    2018-01-01 04:00:00+00:00         1021.7827  ...          621.0280
    ...                                     ...  ...               ...
    2018-12-31 19:00:00+00:00         1610.1920  ...          849.0425
    2018-12-31 20:00:00+00:00         1619.8298  ...          753.1261
    2018-12-31 21:00:00+00:00         1589.6403  ...          664.3381
    2018-12-31 22:00:00+00:00         1513.8585  ...          584.5360
    2018-12-31 23:00:00+00:00         1379.7961  ...          507.9539

    [8760 rows x 10 columns]

Caveats
-------

1. Loads are scaled by the `Floorarea` total of the commercial building
   types only. The `apartment` floor area is excluded because apartment
   loads are already included in `Residential` through the Census housing
   unit counts, and the `no_match` floor area is excluded because
   Comstock has no building type for it (see
   [issue #17](https://github.com/eudoxys/loads/issues/17)).

2. Per-building-type floor areas are not used yet, so the remaining
   commercial floor area is distributed pro rata to the Comstock building
   types in proportion to their Comstock floor areas.

3. The example output above was generated before the fix for issue #17
   and overstates the load in counties with significant apartment or
   unmatched floor area.
"""

import logging

import pandas as pd

from fips import States, Counties
from loads.floorarea import Floorarea
from loads.comstock import COMstock
from cache import Cache

_logger = logging.getLogger(__file__)

class Commercial(pd.DataFrame):
    """Commercial building data frame class

    The `Commercial` class is a data frame that contains the collected
    building loads for each commercial building types, aggregated by load
    category, i.e., `baseload`,`cooling`, `heating`, `dg`, and `total` for
    both electric and non-electric loads.  Values are delivered in MW.
    """
    COLLECT = {
            "elec_baseload": [
                "elec_exteriorlights",
                "elec_fans",
                "elec_heatrejection",
                "elec_equipment",
                "elec_interiorlights",
                "elec_pumps",
                "elec_refrigeration",
                "elec_watersystems",
                ],
            "elec_cooling": [
                "elec_cooling",
                ],
            "elec_heating": [
                "elec_heating",
                "elec_heatrecovery",
                ],
            "elec_dg":[
                ],
            "elec_total": [
                "elec_total",
                ],
            "nonelec_baseload": [
                "district_hotwater",
                "gas_equipment",
                "gas_watersystems",
                "other_watersystems",
                ],
            "nonelec_cooling": [
                "district_cooling",
                ],
            "nonelec_heating": [
                "other_heating",
                "gas_heating",
                "district_heating",
                ],
            "nonelec_dg": [
                ],
            "nonelec_total": [
                "other_total",
                "gas_total",
                "district_totalcooling",
                "district_totalheating",
                ],
            }
    """Mapping of COMstock data columns to Commercial data columns"""

    CACHEDIR = None
    """Cache folder"""

    EXCLUDED_FLOORAREA = ["apartment","no_match"]
    """`Floorarea` building types excluded from the floor area used to scale
    Comstock loads (apartments are included in `Residential` and unmatched
    floor area has no Comstock building type)"""

    _states = None
    """States database"""

    _counties = None
    """Counties database"""

    def __init__(self,
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        state:str,
        county:str,
        *,
        collect:dict[str,list[str]]=None,
        refresh:bool=False,
        ):
        """Construct building types data frame

        Arguments
        ---------

          - `state`: specify the state abbreviation (required)

          - `county`: specify the county name (required)

          - `collect`: specify how COMstock columns are collected (default is `COLLECT`)

          - `refresh`: force cache refresh from source data

        Description
        -----------

        This class compiles the building type data for a county by collecting
        COMstock columns, scaling by the floor area, and computing total
        electric and non-electric loads in MW.

        With the default `collect`, the result is cached as `C.csv.gz`. When
        the file is not in the local cache, it is downloaded from the `cache`
        package archive (the Eudoxys WECC data archive,
        https://github.com/eudoxys/wecc) if the archive has it, and is only
        built from COMstock data if it does not (or if the download fails,
        e.g., offline).

        Caveats
        -------

          - A custom `collect` is never cached or downloaded; it is always
            built from COMstock data.

          - `refresh=True` always rebuilds the result from COMstock data and
            never downloads it from the archive.

          - The archive holds only the latest version of each file, so an
            archived file is assumed to match this cache version.
        """
        # pylint: disable=too-many-locals

        # load state database
        if Commercial._states is None:
            Commercial._states = States()
        if not state in Commercial._states["ST"].values:
            raise ValueError(f"{state=} is not valid")

        # load county database
        if Commercial._counties is None:
            Commercial._counties = Counties().set_index(["ST","COUNTY"])
        if not county in Commercial._counties.loc[state].index.values:
            raise ValueError(f"{state=} {county=} is not valid")

        # load data from cache if default collection is desired
        data = None
        cache = None
        if collect is None:
            collect = self.COLLECT
            if self.CACHEDIR:

                # Note: this update to cachedir needs to be done through
                #       a future change to Cache that cannot be overwritten
                #       by similar actions in other classes that use Cache
                Cache.CACHEDIR = self.CACHEDIR
            cache = Cache(package="loads",version=2,path=[state,county,"C.csv.gz"])
            # download the cache file from the cache archive (the
            # eudoxys/wecc repository) if it is not in the local cache yet
            if not refresh and cache.download():
                if cache.archive:
                    _logger.debug(f"{cache=} downloaded from {cache.archive}")
                try:
                    data = pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0])
                    _logger.debug(f"{cache=} ok")
                except Exception as err:
                    data = None
                    cache.delete()
                    _logger.debug(f"{cache=} {err}")
            else:
                data = None
                _logger.debug(f"{cache=} (re)generation required")

        # load data from Comstock if cache not used
        if data is None:

            # split floor areas by building type
            actual_areas = Floorarea(state=state,county=county)\
                .set_index("BUILDING_TYPE")\
                .sort_index()

            # exclude floor area that is not modeled by Comstock, i.e.,
            # apartments (included in residential loads) and unmatched
            # building types (see issue #17)
            excluded = {"+".join(Floorarea.BUILDING_TYPES[x]) for x in self.EXCLUDED_FLOORAREA}
            total_actual_area = actual_areas.loc[
                ~actual_areas.index.isin(excluded),"FLOORAREA"].sum()

            # read commercial building type data
            data = None
            total_stock_area = 0.0
            for btype in COMstock.BUILDING_TYPES:

                bdata = COMstock(
                    state=state,
                    county=county,
                    building_type=btype,
                    )

                stock_area = bdata["floor_area"]
                total_stock_area += stock_area
                bdata.drop("floor_area",inplace=True,axis=1)

                # convert from W/sf to MW
                bdata = bdata.mul(stock_area,axis=0) / 1e6
                if data is None:
                    data = bdata
                else:
                    data = data.add(bdata,fill_value=0.0)

            # Note: per-building-type areas are not used for now
            #       this will be addressed in a future update

            # construct the reverse mapping of collections
            rmap = {item: key for key, items in collect.items() for item in items}
            if len(rmap) != sum(len(v) for v in collect.values()):
                raise ValueError(f"{collect=} has duplicate entries")

            # group columns to collections
            data.drop([x for x in data.columns if not x in rmap],axis=1,inplace=True)
            data.columns = pd.MultiIndex.from_tuples([(f"{rmap[x]}_MW",x) for x in data.columns])
            data = data.T.groupby(level=0).sum().T
            data = data.reindex(columns=[f"{k}_MW" for k in collect], fill_value=0.0)

            # rescale from stock total area to actual total area
            data = data.div(total_stock_area,axis=0) * total_actual_area

            # update totals (overwrite old values to guarantee consistency)
            data["elec_total_MW"] = sum(data[f"elec_{x}_MW"] for x in ["baseload","cooling","heating"] if f"elec_{x}_MW" in data.columns)
            if "elec_dg_MW" in data.columns:
                data["elec_net_MW"] = data["elec_total_MW"] - data["elec_dg_MW"].abs() # ignore the DG sign from Comstock
            else:
                data["elec_dg_MW"] = 0.0
                data["elec_net_MW"] = data["elec_total_MW"]
            data["nonelec_total_MW"] = sum(data[f"nonelec_{x}_MW"] for x in ["baseload","cooling","heating"] if f"nonelec_{x}_MW" in data.columns)

            # no such thing as non-electric DG
            if "nonelec_dg_MW" in data.columns:
                data.drop("nonelec_dg_MW",axis=1,inplace=True)

            # truncate non-significant digits
            data = data.fillna(0).round(4)

            # save to cache
            if not cache is None:

                # Note: this write is not atomic, this will
                #       be fixed in a future update
                data.to_csv(cache.pathname,
                    index=True,
                    header=True,
                    compression="gzip" if cache.pathname.endswith(".gz") else None,
                    )

        # name the date/time index
        data.index.name = "timestamp"

        # all done
        super().__init__(data[sorted(data.columns)])

    @classmethod
    def makeargs(cls,**kwargs):
        """@private Return dict of accepted kwargs by this class constructor"""
        return {x:y for x,y in kwargs.items()
            if x in cls.__init__.__annotations__}

if __name__ == "__main__":
    """Main script

    The main script refreshes the cache with debugging enabled.
    """

    pd.options.display.width = None
    pd.options.display.max_columns = None

    import sys
    refresh = "--refresh" in sys.argv
    debug = "--debug" in sys.argv
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)

    from fips.counties import Counties

    for state,county in Counties(use_index=["RO","ST","COUNTY"]).loc["WECC"].index.values:
        try:
            df = Commercial(state,county,refresh=refresh)
            if (df.sum()==0).all():
                _logger.warning(f"{state} {county} no data")
            else:
                _logger.info(f"{state} {county} ok")
        except Exception as err:
            (_logger.exception if debug else _logger.error)(f"{state} {county} {err}")
