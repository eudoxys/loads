"""RESstock data accessor

The `RESstock` class is a Pandas data frame loaded with the RESstock
building data.

Residental building types are coded using three characters `R` for
residential, `{'SA','SD','SM','LM','MH'}` for single-family attached,
single-family detached, small multi-family, large multi-family, and
mobile-home. Values are given in W/unit.

Examples
--------

To get the detached single-family home load data for Alameda CA use the command

    from loads.resstock import RESstock
    print(RESstock(state="CA",county="Alameda",building_type="RSD"))

which outputs the following

                               elec_bathfan  ...        units
    2018-01-01 00:00:00+00:00      0.591256  ...  1253270.056
    2018-01-01 01:00:00+00:00      0.973834  ...  1253270.056
    2018-01-01 02:00:00+00:00      1.356412  ...  1253270.056
    2018-01-01 03:00:00+00:00      1.599870  ...  1253270.056
    2018-01-01 04:00:00+00:00      1.634650  ...  1253270.056
    ...                                 ...  ...          ...
    2018-12-31 19:00:00+00:00      0.324611  ...  1253270.056
    2018-12-31 20:00:00+00:00      0.475324  ...  1253270.056
    2018-12-31 21:00:00+00:00      0.486917  ...  1253270.056
    2018-12-31 22:00:00+00:00      0.359391  ...  1253270.056
    2018-12-31 23:00:00+00:00      0.278238  ...  1253270.056

    [8760 rows x 55 columns]

References
----------

  - https://resstock.nlr.gov/
"""

import os
import datetime as dt
import urllib
import logging

import pytz
import pandas as pd

from fips import County
from cache import Cache

_logger = logging.getLogger(__file__)

def _float(s,default=0.0):
    try:
        return float(s)
    except ValueError:
        return default

class RESstock(pd.DataFrame):
    """Construct a RESstock data"""

    # pylint: disable=invalid-name,too-many-locals
    CACHEDIR = None
    """Cache folder path (`None` is package source folder)"""

    SOURCE = "https://oedi-data-lake.s3.amazonaws.com/nrel-pds-building-stock/" \
        "end-use-load-profiles-for-us-building-stock/2021/"\
        "resstock_amy2018_release_1/timeseries_aggregates"
    """URL of data source"""

    COLUMNS = {
        "out.electricity.bath_fan.energy_consumption": "elec_bathfan",
        "out.electricity.ceiling_fan.energy_consumption": "elec_ceilingfan",
        "out.electricity.clothes_dryer.energy_consumption": "elec_dryer",
        "out.electricity.clothes_washer.energy_consumption": "elec_washer",
        "out.electricity.cooking_range.energy_consumption": "elec_cooking",
        "out.electricity.cooling.energy_consumption": "elec_cooling",
        "out.electricity.dishwasher.energy_consumption": "elec_dishwasher",
        "out.electricity.ext_holiday_light.energy_consumption": "elec_holidaylight",
        "out.electricity.exterior_lighting.energy_consumption": "elec_extlighting",
        "out.electricity.extra_refrigerator.energy_consumption": "elec_extrarefrigerator",
        "out.electricity.fans_cooling.energy_consumption": "elec_coolingfan",
        "out.electricity.fans_heating.energy_consumption": "elec_heatingfan",
        "out.electricity.freezer.energy_consumption": "elec_freezer",
        "out.electricity.garage_lighting.energy_consumption": "elec_garagelighting",
        "out.electricity.heating.energy_consumption": "elec_heating",
        "out.electricity.heating_supplement.energy_consumption": "elec_heatingsupplement",
        "out.electricity.hot_tub_heater.energy_consumption": "elec_hottubheater",
        "out.electricity.hot_tub_pump.energy_consumption": "elec_hottubpump",
        "out.electricity.house_fan.energy_consumption": "elec_housefan",
        "out.electricity.interior_lighting.energy_consumption": "elec_interiorlighting",
        "out.electricity.plug_loads.energy_consumption": "elec_plugs",
        "out.electricity.pool_heater.energy_consumption": "elec_poolheater",
        "out.electricity.pool_pump.energy_consumption": "elec_poolpump",
        "out.electricity.pumps_cooling.energy_consumption": "elec_coolingpump",
        "out.electricity.pumps_heating.energy_consumption": "elec_heatingpump",
        "out.electricity.pv.energy_consumption": "elec_pv",
        "out.electricity.range_fan.energy_consumption": "elec_rangefan",
        "out.electricity.recirc_pump.energy_consumption": "elec_recircpump",
        "out.electricity.refrigerator.energy_consumption": "elec_refrigerator",
        "out.electricity.total.energy_consumption": "elec_total",
        "out.electricity.vehicle.energy_consumption": "elec_vehicle",
        "out.electricity.water_systems.energy_consumption": "elec_watersystems",
        "out.electricity.well_pump.energy_consumption": "elec_wellpump",
        "out.fuel_oil.heating.energy_consumption": "oil_heating",
        "out.fuel_oil.total.energy_consumption": "oil_total",
        "out.fuel_oil.water_systems.energy_consumption": "oil_watersystems",
        "out.natural_gas.clothes_dryer.energy_consumption": "gas_dryer",
        "out.natural_gas.cooking_range.energy_consumption": "gas_cooking",
        "out.natural_gas.fireplace.energy_consumption": "gas_fireplace",
        "out.natural_gas.grill.energy_consumption": "gas_grill",
        "out.natural_gas.heating.energy_consumption": "gas_heating",
        "out.natural_gas.hot_tub_heater.energy_consumption": "gas_hottubheater",
        "out.natural_gas.lighting.energy_consumption": "gas_lighting",
        "out.natural_gas.pool_heater.energy_consumption": "gas_poolheater",
        "out.natural_gas.total.energy_consumption": "gas_total",
        "out.natural_gas.water_systems.energy_consumption": "gas_watersystems",
        "out.propane.clothes_dryer.energy_consumption": "lng_dryer",
        "out.propane.cooking_range.energy_consumption": "lng_range",
        "out.propane.heating.energy_consumption": "lng_heating",
        "out.propane.total.energy_consumption": "lng_total",
        "out.propane.water_systems.energy_consumption": "lng_watersystems",
        "out.site_energy.total.energy_consumption": "total",
        "out.wood.heating.energy_consumption": "wood_heating",
        "out.wood.total.energy_consumption": "wood_total",
    }
    """Mapping of res RESstock columns to `RESstock` data frame columns"""

    BUILDING_TYPES = {
        "RSD": "single-family_detached",
        "RSA": "single-family_attached",
        "RSM": "multi-family_with_2_-_4_units",
        "RMM": "multi-family_with_5plus_units",
        "RMH": "mobile_home",
    }
    """Mapping of `RESstock` building types from RESstock building types"""

    def __init__(self,
        state:str,
        county:str=None,
        building_type:list[str]=None,
        refresh:bool=False
        ):
        """Construct a RESstock data frame

        Arguments
        ---------

          - `state`: specifies the state (e.g., "CA")

          - `county`: specifies the county (e.g., "Alameda") or None for the
            entire state

          - `building_type`: specifies the building type (e.g., "house")

          - `refresh`: force download of data from source

        Description
        -----------

        The data frame includes the columns specified by `COLUMNS` constant, which
        maps the RESstock data to the data frame columns. The values are given in
        average Watts per housing unit. The number of units from RESstock is
        given by the `units` column. Note that the number of units is that used
        in the RESstock model, which may not be accurately reflect the actual
        number of units in any given year.
        """
        assert building_type is not None, "building_type must be specified"
        assert building_type in self.BUILDING_TYPES, \
            f"{building_type=} is not one of {self.BUILDING_TYPES}"

        # gather source and cache info
        if self.CACHEDIR :
            Cache.CACHEDIR = self.CACHEDIR
        btype = self.BUILDING_TYPES[building_type]
        if county is None:
            url = f"{self.SOURCE}/by_state/state={state.upper()}/{state.lower()}-{btype}.csv"
            # get whole state data
            cache = Cache(package="loads",version=0,path=[state,f"{building_type}.csv.gz"])
        else:
            fips = County(ST=state,COUNTY=county).FIPS
            url = f"{self.SOURCE}/by_county/state={state.upper()}/g{fips[:2]}0{fips[2:]}0-{btype}.csv"
            # get county-level data
            cache = Cache(package="loads",version=0,path=[state,county,f"{building_type}.csv.gz"])

        # check cache
        if cache.exists() and not refresh:
            try:
                data = pd.read_csv(cache.pathname,dtype=str,na_filter=False,low_memory=False)
                _logger.debug(f"{cache=} ok")
            except Exception as err:
                _logger.debug(f"{cache=} {err}")
                cache.delete()
                data = None
        else:
            _logger.debug(f"{cache=} (re)generation required")
            data = None

        # download if needed
        maxretry = 5
        retry = 0
        error = None
        while data is None and retry < maxretry:

            # download data to cache
            try:
                data = pd.read_csv(url)
                data.to_csv(cache.pathname,compression="gzip" if cache.pathname.endswith(".gz") else None)
                _logger.debug(f"{url=} download ok")
            except urllib.error.HTTPError as err:
                data = None
                if str(err) == "HTTP Error 404: Not Found":
                    break
                error = err
                retry += 1

        if retry >= maxretry or error:
            # download error (most likely no data in COMstock)
            _logger.error(f"RESstock {county} {state} '{btype}' ({building_type}) data not available ({error}) after {retry} download attempts")            


        if data is None:

            # create all zeros dataframe
            ndx = pd.date_range(
                start="2018-01-01 05:00:00+00:00",
                end="2019-01-01 04:00:00+00:00",
                freq="1h")
            zeros = [0.0]*len(ndx)
            data = pd.DataFrame(data={x:zeros for x in self.COLUMNS},index=ndx)
            data.index.name = "timestamp"
            data["units_represented"] = units = 0.0

        else:
            # restructure index
            data.set_index("timestamp",inplace=True)
            data.index = (pd.DatetimeIndex(data.index,tz=pytz.timezone("EST")) \
                - dt.timedelta(minutes=15)).tz_convert(pytz.UTC)

            # capture number of housing units
            units = data["units_represented"].astype(float)
            if units.min() != units.max():
                _logger.debug(f"{state=} {county=} number of units changes (using max)")
            units = units.max()
            if units == 0.0:
                _logger.debug(f"{state} {county} {building_type} has no units")

        # restructure data
        data.drop([x for x in data.columns if x not in self.COLUMNS],inplace=True,axis=1)
        data.rename(self.COLUMNS,inplace=True,axis=1)
        for value in self.COLUMNS.values():
            data[value] = [_float(x)/units*1000 for x in data[value]] if units > 0 else 0.0

        # recover number of units represented
        data["units"] = units

        # resample to hourly frequency
        data = data.resample("1h").sum()

        # move year-end data to beginning
        data.index = pd.DatetimeIndex([str(x).replace("2019","2018") for x in data.index])
        super().__init__(data.sort_index())

    @classmethod
    def makeargs(cls,**kwargs):
        """@private Return dict of accepted kwargs by this class constructor"""
        return {x:y for x,y in kwargs.items()
            if x in cls.__init__.__annotations__}

if __name__ == "__main__":
    """RESstock main script

    The main script refreshes the cache with debugging enabled.
    """
    import sys
    refresh = "--refresh" in sys.argv
    debug = "--debug" in sys.argv
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)

    from fips.counties import Counties

    logging.basicConfig(level=logging.INFO)

    for state,county in Counties(use_index=["RO","ST","COUNTY"]).loc["WECC"].index.values:
        for btype in RESstock.BUILDING_TYPES:
            try:
                RESstock(state,county,building_type=btype,refresh=refresh)
                _logger.debug(f"{state} {county} {btype} ok")
            except Exception as err:
                (_logger.exception if debug else _logger.error)(f"{state} {county} {btype}: {err}")
