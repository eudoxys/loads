"""Distributed generation

This module provides the hourly distributed generation (DG) of a county, i.e.,
the small-scale (behind-the-meter) solar output that is not included in the
EIA Form 860 and Form 923 data, as the `elec_dg_MW` column used by
`loads.total.Total`.

The method follows the REGROW EIA-861M small-scale solar procedure
(`data/EIA861M_SmallScaleSolar.md` in `slacgismo/regrow`), which allocates
the monthly state small-scale PV generation reported by EIA to network busses
in proportion to load. Here the manual download, concatenation and filtering
steps of that procedure are automated with `eia.Form861m`, the allocation is
made to counties instead of busses, and the monthly energy is given an hourly
shape.

Data Flow
---------

```mermaid
flowchart LR
    EIA[("EIA Form 861M<br/>small-scale PV")] -->|state MWh/month| SSS[SmallScaleSolar]
    MWH[("wecc/county_mwh.csv")] -->|county share of state load| DG
    SSS --> DG
    NSRDB[("NSRDB GHI")] -->|profile=weather| DG
    DGEN[("wecc/county_dg.csv.gz")] -->|profile=dgen| DG
    DG -->|elec_dg_MW| Total
    DG -->|compile| FILE[county DG file]
```

Description
-----------

For state $s$, county $c$, month $m$, and hour $h \\in m$ the DG is

$$
    D_{ch} = - E_{sm} w_{cm} \\frac{p_{ch}}{\\sum_{k \\in m} p_{ck}}
$$

where

  - $E_{sm}$ is the EIA-861M total small-scale PV generation of the state
    (MWh, all sectors),

  - $w_{cm}$ is the county's share of the state's monthly electric energy
    use (`wecc/county_mwh.csv`), which is the county counterpart of the bus
    `load_fraction` used by REGROW, and

  - $p_{ch} \\geq 0$ is the hourly profile of the county, either the NSRDB
    global horizontal irradiance (`profile="weather"`, the default) or the
    NLR dGen rooftop PV output (`profile="dgen"`, `wecc/county_dg.csv.gz`).

The monthly county DG energy therefore matches EIA exactly, and the hourly
shape follows the county's sunshine. The sign follows the package convention
that DG is a negative load, i.e., $D_{ch} \\leq 0$ and
`elec_net_MW = elec_total_MW + elec_dg_MW`.

Examples
--------

To get the hourly DG of Alameda County CA in 2020 use

    import pandas as pd
    from loads.dgen import DG
    date_range = pd.date_range("2020-01-01 00:00:00+00:00",
        "2020-12-31 23:00:00+00:00",freq="1h")
    DG("CA","Alameda",date_range)

which returns 8784 hourly rows with the single column `elec_dg_MW`.

To add the DG to a total load data frame, e.g., a `loads.total.Total`
prediction, and recompute the net load use

    from loads.total import Total
    total = Total("CA","Alameda",date_range=date_range,samples=0)
    total = DG.merge(total,"CA","Alameda")

which replaces (or adds) `elec_dg_MW` and, when `elec_total_MW` is present,
sets `elec_net_MW = elec_total_MW + elec_dg_MW`.

To compile the DG of every WECC county for 2018 through 2022 into a single
file (one `County ST` column per county, nonnegative MW as expected by the
`dg` argument of `loads.calibrate.Calibrate`) use

    python3 -m loads.dgen --target=county_dg_eia.csv.gz

To use a local copy of the EIA data instead of downloading it, e.g., the
REGROW `data/wecc_dg_solar.csv` file, add `--source=wecc_dg_solar.csv`.

Caveats
-------

  - EIA reports calendar months in local time, but months are taken in UTC
    here. This moves a few early-evening hours on the last day of each month
    into the next month, which changes the monthly energy by much less than
    1%.

  - The county shares come from the bundled `wecc/county_mwh.csv`, which
    covers 2018 through 2022. Months outside that range use the share of the
    same calendar month in the nearest year. Counties not in that file get
    no DG and a warning.

  - The `"weather"` profile treats DG output as proportional to global
    horizontal irradiance, i.e., it ignores panel orientation and
    temperature derating. The `"dgen"` profile is only available for 2018
    through 2022, and counties that are missing or all zero in the dGen file
    (e.g., Garfield WA) use the total profile of the dGen counties in their
    state.

  - Wind DG is not included.

References
----------

  - https://www.eia.gov/electricity/data/eia861m/

  - https://github.com/slacgismo/regrow/blob/main/data/EIA861M_SmallScaleSolar.md
"""

import os
import sys
import logging
from warnings import warn

import pandas as pd

from fips import States, Counties
from weather import Weather
from eia import Form861m
from cache import Cache

_logger = logging.getLogger(__file__)

PACKAGEDIR = os.path.dirname(os.path.abspath(__file__))
"""@private Package folder"""

COUNTY_MWH = os.path.join(PACKAGEDIR,"wecc","county_mwh.csv")
"""Monthly county energy use (MWh) used to allocate state DG to counties"""

DGEN_PROFILES = os.path.join(PACKAGEDIR,"wecc","county_dg.csv.gz")
"""Hourly NLR dGen county rooftop PV output (MW) used by `profile="dgen"`"""


class SmallScaleSolar(pd.DataFrame):
    """EIA-861M monthly small-scale solar data frame

    The data frame is indexed by `month` (a monthly `pd.Period`) and `state`,
    and has the capacity columns `res_mw`, `com_mw`, `ind_mw`, `tot_mw` (MW),
    and the generation columns `res_mwh`, `com_mwh`, `ind_mwh`, `tot_mwh`
    (MWh) of the residential, commercial, industrial and all sectors.
    """
    COLUMNS = ["res_mw","com_mw","ind_mw","tot_mw","res_mwh","com_mwh","ind_mwh","tot_mwh"]
    """Data columns"""

    _data = {}

    def __init__(self,
        year:int|list[int],
        state:str|list[str]|None=None,
        source:str|None=None,
        refresh:bool=False,
        ):
        """Construct an EIA-861M small-scale solar data frame

        Arguments
        ---------

          - `year`: year or list of years (EIA-861M data starts in 2017)

          - `state`: state or list of states (default all states)

          - `source`: local EIA-861M data file (CSV or Excel) laid out as the
            EIA "Monthly Totals- States" sheet, i.e., the columns `Year`,
            `Month`, `State`, `Data Status`, followed by the residential,
            commercial, industrial and total capacity (MW), and the same
            for generation (MWh). The default `None` downloads the data from
            EIA using `eia.Form861m`.

          - `refresh`: refresh the data downloaded from EIA
        """
        years = [year] if isinstance(year,int) else sorted(set(year))
        if source is None:
            data = pd.concat([self._get_eia(x,refresh) for x in years])
        else:
            data = self._get_source(source,refresh)
            data = data[data.index.get_level_values("month").year.isin(years)]
        if state is not None:
            states = [state] if isinstance(state,str) else list(state)
            data = data[data.index.get_level_values("state").isin(states)]
        super().__init__(data.sort_index())

    @classmethod
    def _get_eia(cls,year:int,refresh:bool) -> pd.DataFrame:
        """@private Get a year of EIA-861M data from EIA"""
        if year not in cls._data or refresh:
            data = []
            for month in range(1,13):
                try:
                    data.append(Form861m(year,month,refresh=refresh))
                except (AssertionError,KeyError) as err:
                    # month not published yet
                    _logger.debug(f"Form861m({year},{month}) {err}")
            if not data:
                raise ValueError(f"EIA-861M has no small-scale solar data for {year=}")
            data = pd.concat(data)
            data["month"] = pd.DatetimeIndex(data["date"]).tz_localize(None).to_period("M")
            cls._data[year] = data.set_index(["month","state"])[cls.COLUMNS]
        return cls._data[year]

    @classmethod
    def _get_source(cls,source:str,refresh:bool) -> pd.DataFrame:
        """@private Get EIA-861M data from a local file"""
        if source not in cls._data or refresh:
            if source.endswith((".xls",".xlsx")):
                data = pd.read_excel(source,sheet_name="Monthly Totals- States",
                    skiprows=3,header=None)
            else:
                data = pd.read_csv(source,encoding="utf-8-sig",dtype=str)
            data = data.iloc[:,:12]
            data.columns = ["year","month","state","status"] + cls.COLUMNS
            data = data.dropna(subset=["year","month","state"])
            data = data[pd.to_numeric(data["year"],errors="coerce").notna()]
            for column in cls.COLUMNS:
                data[column] = pd.to_numeric(data[column].astype(str).str.replace(",",""),
                    errors="coerce").fillna(0.0)
            data["month"] = pd.PeriodIndex.from_fields(
                year=data["year"].astype(float).astype(int),
                month=data["month"].astype(float).astype(int),
                freq="M")
            data["state"] = data["state"].str.strip()
            cls._data[source] = data.set_index(["month","state"])[cls.COLUMNS]
        return cls._data[source]


class DG(pd.DataFrame):
    """Distributed generation data frame

    The data frame is indexed by the UTC `timestamp` and has the single column
    `elec_dg_MW` (never positive).
    """
    CACHEDIR = None
    """Folder in which results are cached (default is the `cache` package default)"""

    PROFILES = ["weather","dgen"]
    """Valid hourly profile sources"""

    TRAINING_YEAR = 2018
    """Year used when no `date_range` is given (same as `loads.total.Total`)"""

    _county_mwh = None
    _dgen = None

    def __init__(self,
        state:str,
        county:str,
        date_range:pd.DatetimeIndex|None=None,
        profile:str="weather",
        source:str|None=None,
        refresh:bool=False,
        ):
        """Construct a county distributed generation data frame

        Arguments
        ---------

          - `state`: state abbreviation

          - `county`: county name

          - `date_range`: hourly date/time index (default is all of
            `DG.TRAINING_YEAR`; naive times are taken as UTC)

          - `profile`: hourly profile source, `"weather"` (NSRDB global
            horizontal irradiance) or `"dgen"` (NLR dGen rooftop PV output
            in `wecc/county_dg.csv.gz`, 2018-2022 only)

          - `source`: local EIA-861M data file (see `SmallScaleSolar`); the
            default `None` downloads it from EIA

          - `refresh`: regenerate the cached county DG

        Returns
        -------

        The data frame contains the `elec_dg_MW` column of the county for the
        hours in `date_range`. DG is a negative load, so values are zero or
        negative. Hours in months for which EIA has no data are `NaN`.
        """
        assert state in States()["ST"].values, f"{state=} is not valid"
        assert county in Counties().set_index(["ST","COUNTY"]).loc[state].index, \
            f"{county=} is not valid in {state=}"
        assert profile in self.PROFILES, f"{profile=} is not valid"

        if self.CACHEDIR:
            Cache.CACHEDIR = self.CACHEDIR

        if date_range is None:
            date_range = self._year_range(self.TRAINING_YEAR)
        date_range = pd.DatetimeIndex(date_range)
        if date_range.tz is None:
            date_range = date_range.tz_localize("UTC")
        else:
            date_range = date_range.tz_convert("UTC")

        data = pd.concat([self._get_year(state,county,year,profile,source,refresh)
            for year in sorted(set(date_range.year))])
        data = data[~data.index.duplicated()].reindex(date_range)

        super().__init__(data.rename_axis("timestamp"))

    @classmethod
    def merge(cls,
        data:pd.DataFrame,
        state:str,
        county:str,
        **kwargs,
        ) -> pd.DataFrame:
        """Add the county DG to a load data frame

        Arguments
        ---------

          - `data`: hourly load data frame indexed by timestamp, e.g., a
            `loads.total.Total` result

          - `state`: state abbreviation

          - `county`: county name

          - `**kwargs`: other `DG` arguments (`profile`, `source`, `refresh`)

        Returns
        -------

          - `pd.DataFrame`: a copy of `data` in which `elec_dg_MW` is replaced
            (or added) and, when `elec_total_MW` is present, `elec_net_MW` is
            set to `elec_total_MW + elec_dg_MW`
        """
        result = data.copy()
        dg = cls(state,county,date_range=pd.DatetimeIndex(result.index),**kwargs)
        result["elec_dg_MW"] = dg["elec_dg_MW"].values
        if "elec_total_MW" in result.columns:
            result["elec_net_MW"] = result["elec_total_MW"] + result["elec_dg_MW"]
        return result

    @staticmethod
    def _year_range(year:int) -> pd.DatetimeIndex:
        """@private Hourly UTC index of a year"""
        return pd.date_range(f"{year}-01-01 00:00:00+00:00",
            f"{year}-12-31 23:00:00+00:00",freq="1h",name="timestamp")

    @classmethod
    def _get_year(cls,
        state:str,
        county:str,
        year:int,
        profile:str,
        source:str|None,
        refresh:bool,
        ) -> pd.DataFrame:
        """@private Get a year of county DG (cached)"""
        cache = Cache(package="loads",version=0,path=[state,county,f"DG_{profile}_{year}.csv.gz"])
        data = None
        if not refresh and cache.download():
            try:
                data = pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0])
                data.index = pd.DatetimeIndex(data.index).tz_convert("UTC")
                _logger.debug(f"{cache=} ok")
            except Exception as err: # pylint: disable=broad-exception-caught
                data = None
                cache.delete()
                _logger.debug(f"{cache=} {err}")
        else:
            _logger.debug(f"{cache=} (re)generation required")

        if data is None:

            # hourly profile and the month of each hour
            hourly = cls._get_profile(state,county,year,profile)
            month = hourly.index.tz_localize(None).to_period("M")
            months = month.unique()

            # monthly state small-scale solar generation
            eia = SmallScaleSolar(year,state=state,source=source)["tot_mwh"]
            eia = eia.droplevel("state").reindex(months)
            if eia.isna().any():
                warn(f"EIA-861M has no {state} data for "
                    f"{', '.join(str(x) for x in eia.index[eia.isna()])}")

            # monthly county DG energy
            energy = eia * cls._get_share(state,county,months)

            # hourly DG shaped by the profile
            total = hourly.groupby(month).transform("sum")
            dg = hourly / total.where(total > 0) * energy.reindex(month).values
            data = pd.DataFrame({"elec_dg_MW":0.0 - dg.round(6)},index=hourly.index)
            data.index.name = "timestamp"

            # incomplete years are not cached so missing EIA data is retried later
            if data["elec_dg_MW"].notna().all():
                data.to_csv(cache.pathname,index=True,header=True,
                    compression="gzip" if cache.pathname.endswith(".gz") else None)

        return data

    @classmethod
    def _get_share(cls,
        state:str,
        county:str,
        months:pd.PeriodIndex,
        ) -> pd.Series:
        """@private Monthly county share of the state energy use"""
        if cls._county_mwh is None:
            mwh = pd.read_csv(COUNTY_MWH,index_col=[0])
            # drop columns duplicated by pandas (e.g., "Pinal AZ.1"), if any
            mwh = mwh[[x for x in mwh.columns if not x.rsplit(".",1)[-1].isdigit()]]
            mwh.index = pd.PeriodIndex(pd.to_datetime(mwh.index,format="%b %Y"),freq="M")
            cls._county_mwh = mwh

        mwh = cls._county_mwh
        county_st = f"{county} {state}"
        if county_st not in mwh.columns:
            warn(f"{county_st} is not in {os.path.basename(COUNTY_MWH)} (no DG allocated)")
            return pd.Series(0.0,index=months)
        members = [x for x in mwh.columns if x.rsplit(" ",1)[1] == state]
        share = mwh[county_st] / mwh[members].sum(axis=1)

        # months outside the data use the same month of the nearest year
        first,last = share.index.min().year,share.index.max().year
        lookup = [pd.Period(year=min(max(x.year,first),last),month=x.month,freq="M")
            for x in months]
        return pd.Series(share.reindex(lookup).values,index=months)

    @classmethod
    def _get_profile(cls,
        state:str,
        county:str,
        year:int,
        profile:str,
        ) -> pd.Series:
        """@private Hourly nonnegative profile of a county for a year"""
        index = cls._year_range(year)

        if profile == "weather":
            data = Weather(state,county,year)["global_Wpms"]

        elif profile == "dgen":
            if cls._dgen is None:
                dgen = pd.read_csv(DGEN_PROFILES,index_col=[0],parse_dates=[0])
                dgen.index = pd.DatetimeIndex(dgen.index).tz_convert("UTC")
                cls._dgen = dgen
            dgen = cls._dgen
            if year not in set(dgen.index.year):
                raise ValueError(f"{os.path.basename(DGEN_PROFILES)} has no data for {year=}")
            dgen = dgen[dgen.index.year == year]
            county_st = f"{county} {state}"
            if county_st in dgen.columns and dgen[county_st].sum() > 0:
                data = dgen[county_st]
            else:
                members = [x for x in dgen.columns if x.rsplit(" ",1)[1] == state]
                if not members:
                    raise ValueError(f"{os.path.basename(DGEN_PROFILES)} has no data for {state=}")
                _logger.debug(f"{county_st} has no dGen profile in {year}, using {state} total")
                data = dgen[members].sum(axis=1)

        else:
            raise ValueError(f"{profile=} is not valid")

        data.index = pd.DatetimeIndex(data.index)
        data.index = data.index.tz_localize("UTC") if data.index.tz is None \
            else data.index.tz_convert("UTC")
        data = data[~data.index.duplicated()]
        return data.reindex(index).fillna(0.0).clip(lower=0.0)


def compile( # pylint: disable=redefined-builtin
    years:list[int]|tuple[int,int]=(2018,2022),
    target:str|None="county_dg_eia.csv.gz",
    profile:str="weather",
    system:str="WECC",
    source:str|None=None,
    refresh:bool=False,
    ) -> pd.DataFrame|None:
    """Compile the hourly DG of all the counties in a system

    Arguments
    ---------

      - `years`: first and last year to compile

      - `target`: output file name (`None` returns the data frame instead of
        saving it)

      - `profile`: hourly profile source (see `DG`)

      - `system`: system for which counties are compiled

      - `source`: local EIA-861M data file (see `SmallScaleSolar`)

      - `refresh`: regenerate the cached county DG

    Returns
    -------

      - `pd.DataFrame`: hourly DG output (MW, nonnegative) with one
        `County ST` column per county, when `target` is `None`

    Counties that fail are logged and omitted.
    """
    date_range = pd.date_range(f"{min(years)}-01-01 00:00:00+00:00",
        f"{max(years)}-12-31 23:00:00+00:00",freq="1h",name="timestamp")
    counties = Counties(use_index=["SYSTEM"],selection=[system])[["ST","COUNTY"]]

    result = {}
    for state,county in sorted(counties.values.tolist()):
        try:
            result[f"{county} {state}"] = -DG(state,county,date_range,
                profile=profile,source=source,refresh=refresh)["elec_dg_MW"]
            _logger.info(f"{county} {state} ok")
        except Exception as err: # pylint: disable=broad-exception-caught
            _logger.error(f"{county} {state} {err}")
    result = pd.DataFrame(result,index=date_range).round(3)

    if target is None:
        return result
    result.to_csv(target,index=True,header=True,
        compression="gzip" if target.endswith(".gz") else None)
    return None


if __name__ == "__main__":

    def _option(name,default=None):
        for arg in sys.argv[1:]:
            if arg.startswith(f"--{name}="):
                return arg.split("=",1)[1]
        return default

    logging.basicConfig(level=logging.DEBUG if "--debug" in sys.argv else logging.INFO)

    compile(
        years=[int(x) for x in _option("years","2018,2022").split(",")],
        target=_option("target","county_dg_eia.csv.gz"),
        profile=_option("profile","weather"),
        system=_option("system","WECC"),
        source=_option("source"),
        refresh="--refresh" in sys.argv,
        )
