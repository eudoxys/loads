r"""Load calibration module

The `loads.calibrate` module is used to rescale loads to match know energy
consumptions over a specified time period.  The rescaling is performed such
that for each column of the data table with a name ending in `'_MW'`

$$
    P_{new}  = P_{old} ~ \frac {E_{new}} {E_{old}}
$$

when $E_{old} /ne 0$, where

  - $P_{new}$ is the new load data,

  - $P_{old}$ is the old load data,

  - $E_{new}$ is the new energy consumption, and

  - $E_{old}$ is the old energy consumption.

The values of $E_{old}$ and $E_{new}$ are the sum of the $P_{old}$ and $P_{new}$, respectively, over the date/time range given, or the entire data frame if no date/time range is given.

Examples
--------

To calibrate a load to a known `total_energy` and `peak_demand`:

    Calibrate(load,
        energy={"elec_net_MW":total_energy},
        peak={"elec_net_MW":peak_demand},
        )

To calibrate a load with a known `scale` and `offset`:

    Calibrate(load,scale=scale,offset=offset)

"""

import datetime as dt
import numpy as np
import pandas as pd
import logging

from fips import States, Counties
from eia import HS861m
from loads.residential import Residential
from loads.commercial import Commercial
from cache import Cache

_logger = logging.getLogger(__file__)

def integrate(data,range=None,rename=False):
    """Integrate data frame over time range

    Arguments
    ---------

      - `data`: data frame over which to integrate power values(assuming uniform
        1h intervals)

      - `range`: date/time index range over which to integrate

      - `rename`: rename columns to their integrals, i.e., `'*_MW'` becomes
        `*_MWh`

    Returns
    -------

      - `pd.DataFrame`: the resulting power integrals over time as single row

    Description
    -----------

    The time-integration of a power dataframe results in an energy value. Use
    the `rename=True` option to enable renaming the columns to use energy
    units instead of power units.
    """

    # select the data range to process
    samples = data.loc[... if range is None else range,data.columns] 

    # sample the data range
    result = samples.sum(axis=0).to_frame().T

    # rename the columns if desired
    if rename:
        result.columns = [f"{x}h" for x in result.columns]

    # identify the start and end date/times and use it as the index name
    start = samples.index[0].strftime(Calibrate.DATETIME_FORMAT)
    end = samples.index[-1].strftime(Calibrate.DATETIME_FORMAT)
    result.index = [f"sum({start=},{end=},freq='1h')"]

    return result

def fit_load(x, *,
             energy:float|None=None, 
             peak:float|None=None, 
             precision:float=1e-3, 
             maxiter:int=100,
             damping:float = 1.0,
             exception:Exception|None=RuntimeError,
             constraints:list[str]=None,
            ) -> [float,float]:
    """Fit load to energy and/or peak constraints

    Arguments
    ---------

      - `energy`: energy constraint

      - `peak`: peak constraint

      - `precision`: energy error

      - `maxiter`: maximum iterations

      - `damping`: error correct damping coefficient

      - `exception`: exception to use

      - `constraints`: constraints on resulting load

    Returns
    -------

      - `np.array|None`: fit load or None if maximum iterations reached
        without exception handler

      - `float`: energy error

    Description
    -----------

    The load data `x` the rescaled and offset to such that the sum of the `x`
    is equal to the energy and the peak of `x` is equal to the peak. Note
    that the peak is defined as the value which occurs at the maximum `x`
    prior to rescaling, meaning that after rescaling the peak may shift and
    may be greater than the rescaled value of the original peak (i.e., the
    resulting load shape is inverted).

    Two constraints are supported:

      - `positive`: the resulting value may not be zero or negative.

      - `inverted`: the resulting peaks may not be inverted.

    Violating these constraints raises an exception.

    Caveats
    -------

      - It is possible for the fit to have negative values or inverted peaks
        if the energy and peak constraints are not otherwise feasible. You can use the `constraints` to raise an exception or return None when this occurs, making these fits infeasible.
    """
    if constraints is None:
        constraints = []
    assert isinstance(constraints,list), f"{constraints=} must be a list of strings"
    for constraint in constraints:
        assert constraint in ["positive","inverted"], f"{constraint=} in invalid"

    y0 = min(x)
    N = len(x)
    if energy is None:
        energy = x.sum()
    if peak is None:
        peak = x.max()
    y = np.array(x - max(x)) / (min(x) - max(x))  # normalized x
    denormalize = lambda x, b: x * (b-peak) + peak
    e = lambda x, b: energy - sum(denormalize(x, b))
    iter = 1
    while abs(err:=e(y, y0)) > precision:
        y0 += err / N / damping  # correction to min
        iter += 1
        if iter > maxiter:
            if exception:
                raise exception(f"{maxiter=} reached")
            return None,err
    y = denormalize(y, y0)
    err = float(err)
    
    assert "inverted" not in constraints or min(y) <= max(y), \
        f"constraint='inverted' violated {min(y)=} > {max(y)=}"
    
    assert "positive" not in constraints or min(y) > 0.0, \
        f"constraint='positive' violated {min(y) <= 0}"

    return y,err

class Calibrate(pd.DataFrame):
    """Load calibration data frame"""

    CACHEDIR = None

    DATETIME_INDEX = "timestamp"
    """Name of date/time index column"""

    DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S%z"
    """The date/time format of start/end integration range values"""

    def __init__(self,
        load:pd.DataFrame,
        energy:dict[str,float]|None=None,
        peak:dict[str,float]|None=None,
        scale:float=1.0,
        offset:float=0.0,
        start:dt.datetime|str=None,
        end:dt.datetime|str=None,
        ):
        r"""Construct a calibrated load data frame

        Arguments
        ---------

          - `load`: old uncalibrated load data

          - `energy`: new energy consumption to calibrate load with

          - `peak`: new peak load to calibration load with

          - `scale`: scalar to apply to final result

          - `offset`: constant offset to apply to scaled final result

          - `start`: start date of new energy consumption

          - `end`: end date of new energy consumption
        """

        data = load.copy().reset_index().set_index(self.DATETIME_INDEX)
        
        assert isinstance(scale,(float,int)), f"{scale=} is invalid"
        assert isinstance(offset,(float,int)), f"{offset=} is invalid"

        if not energy is None or not peak is None:
            if start is None:
                start = data.index[0]
            elif isinstance(start,str):
                start = pd.datetime.strptime(start,self.DATETIME_FORMAT)
            assert isinstance(start,(dt.datetime,np.datetime64)), f"{start=} is invalid"
            if end is None:
                end = data.index[-1]
            elif isinstance(end,str):
                end = pd.datetime.strptime(end,self.DATETIME_FORMAT)
            assert isinstance(end,(dt.datetime,np.datetime64)), f"{end=} is invalid"
            assert start < end, f"{start=} must be before {end=}"

            date_range = pd.date_range(start,end,freq="1h")
            for column in set(energy.keys())|set(peak.keys()):
                try:
                    data[column],_ = fit_load(
                        data.loc[date_range][column],
                        energy=energy[column] if column in energy else None,
                        peak=peak[column] if column in peak else None,
                        constraints=["positive","inverted"],
                        )
                except RuntimeError as err:
                    energy = energy[column] if column in energy else None
                    peak = peak[column] if column in peak else None
                    _logger.debug(f"unable to fit {column=} to {energy=} and {peak=}")
                    raise

        super().__init__(data*scale+offset)

    CACHE = {}

    @classmethod
    def state(cls,
        state:str,
        year:int|None=None,
        refresh:bool=False,
        ) -> pd.DataFrame:
        """Compute state load calibration values

        Arguments
        ---------

          - `state`: state for which to compute calibrations

          - `year`: the year for which loads are calibrated

          - `refresh`: force refresh of cache

        Returns
        -------

          - `pd.DataFrame`: data frame contain sector calibration factor

        Description
        -----------

        The residential and commercial load data is obtained from the NLR
        RESstock and COMstock data repositories. These data set have not been
        calibrated against the state-level EIA energy use. The
        `loads.calibrate.Calibrate.state` function is used to obtain the
        state-level calibrations for any given year available from EIA. See
        `eia.hs860m.HS860m` for details.

        Caveats
        -------

        - The methodology requires that all the loads for each county in the
          state be loaded before any scalars can be computed. This can take a
          long time to complete states with many counties, e.g., Texas.

        - Only residential (`'R'`) and commercial (`'C'`) load calibations can
          be computed. Industry (`'I'`) and agriculture (`'A'`) come from EIA
          sources at the state-level and cannot be independently recalibrated
          at the county level. 

        - Transportation is not included in the load model at this time, despite
          the availability of state-level transportation energy consumption.
        """
        if state in cls.CACHE:
            return cls.CACHE[state]

        sector_specs = {
            "R":(Residential,"res_energy_mwh"),
            "C":(Commercial,"com_energy_mwh"),
        }

        # set cache location
        if cls.CACHEDIR :
            Cache.CACHEDIR = cls.CACHEDIR
        result = []
        for sector,specs in sector_specs.items():
            cache = Cache(
                package="loads",
                version=0,
                path=[
                    state,
                    f"calibrate_{sector}.csv" 
                        if year is None 
                        else f"calibrate_{sector}_{year}.csv" ],
                )
            if cache.exists() and not refresh:
                result.append(pd.read_csv(cache.pathname))
            else:
                old_energy = 0.0
                for county in Counties(use_index=["ST"]).loc[state]["COUNTY"]:
                    old_energy += specs[0](state,county,year)["elec_total_MW"].sum()
                new_energy = 0.0
                for month in range(1,13):
                    new_energy += HS861m(year if year else 2018,month).loc[state,specs[1]]

                scalar = new_energy / old_energy
                result.append(pd.DataFrame(
                    data={"scalar":[scalar],"state":[state],"sector":[sector]},
                    index=[len(result)]))
                result[-1].to_csv(cache.pathname,index=False,header=True)
        result = pd.concat(result)
        cls.CACHE[state] = result.drop("state",axis=1).set_index(["sector"])
        return cls.CACHE[state]

if __name__ == '__main__':
    
    pd.options.display.max_columns = None
    pd.options.display.width = None

    import sys
    refresh = "--refresh" in sys.argv
    debug = "--debug" in sys.argv
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)

    states = sorted(Counties(use_index="SYSTEM").loc["WECC"]["ST"].unique())
    for year in range(2020,2023):
        for state in states:
            Calibrate.state(state,year=year,refresh=refresh).reset_index()
            _logger.info(f"{state} {year} ok")
