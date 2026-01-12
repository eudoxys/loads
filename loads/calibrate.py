r"""Load calibration module

The `calibration` module is used to rescale loads to match know energy
consumptions over a specified time period.  The rescaling is performed such
that for each column of the data table with a name ending in `'_MW'`

$$
    \frac {P_{new}} {P_{old}} = \frac {E_{new}} {E_{old}}
$$

where

  - $P_{new}$ is the new load data

  - $P_{old}$ is the old load data

  - $E_{new}$ is the new energy consumption

  - $E_{old}$ is the old energy consumption
"""

import datetime as dt
import numpy as np
import pandas as pd
from fips import States, Counties

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
    the `rename=True` option to enable renaming the columns to their energy.
    The index name indicates the date/time range over which the integration was
    performed.
    """

    # only handle columns names that end in a power unit
    columns = [x for x in data.columns if x.endswith("W")]

    # select the data range to process
    samples = data.loc[... if range is None else range,columns] 

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

class Calibrate(pd.DataFrame):
    """Load calibration data frame"""

    DATETIME_INDEX = "timestamp"
    """Name of date/time index column"""

    DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S%z"
    """The date/time format of start/end integration range values"""

    def __init__(self,
        load:pd.DataFrame,
        energy:float|None=None,
        scale:float=1.0,
        start:dt.datetime|str=None,
        end:dt.datetime|str=None,
        ):
        """Construct a calibrated load data frame

        Arguments
        ---------

          - `load`: old uncalibrated load data

          - `energy`: new energy consumption to calibrate load with

          - `scale`: scalar to apply to final result

          - `start`: start date of new energy consumption

          - `end`: end date of new energy consumption
        """

        data = load.copy().reset_index().set_index(self.DATETIME_INDEX)
        
        assert isinstance(scale,float), f"{scale=} is invalid"
        if not energy is None:
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
            assert len(new_energy) == 1 and (new_energy.columns == data.columns).all(), f"new_energy is not valid"

            date_range = pd.date_range(start,end,freq="1h")
            old_energy = integrate(data,date_range)

            for column in [x for x in data.columns if x.endswith("_MW")]:
                value = old_energy[column].values[0]
                if value != 0:
                    data[column] *= energy[column].values[0] / value

        super().__init__(data*scale)

    @staticmethod
    def state(
        state:str,
        sectors:list[str]|None=None,
        year:int|None=None,
        ) -> pd.DataFrame:
        """Compute state load calibration values

        Arguments
        ---------

          - `state`: state for which to compute calibrations

          - `sectors`: list of sector for which calibrations are desired

          - `year`: the year for which loads are calibrated

        Returns
        -------

          - `pd.DataFrame`: data frame contain sector calibration factor

        Description
        -----------

        The residential and commercial load data is obtained from the NLR
        RESstock and COMstock data repositories. These data set have not been
        calibrated against the state-level EIA energy use. The `loads.calibrate.Calibrate.state` function is used to obtain the
        state-level calibrations for any given year available from EIA. See `eia.hs860m.HS860m` for details.

        Caveats
        -------

        - The methodology requires that all the loads for each county in the
          state be loaded before any scalars can be computed. This can take a
          long time to complete.

        - By default only residential (`'R'`) and commercial (`'C'`) load
          calibations are computed. Industry (`'I'`) is also available but
          usually does not need to be computed since the uncalibrated
          industrial and agricultural loads come from EIA as well.
        """
        sector_specs = {
            "R":(Residential,"res_energy_mwh"),
            "C":(Commercial,"com_energy_mwh"),
        }
        result = []
        for sector in sectors if sectors else sector_specs:
            specs = sector_specs[sector]
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
        return pd.concat(result).set_index(["state","sector"])

if __name__ == '__main__':
    
    from fips import Counties
    from eia import HS861m
    from loads.residential import Residential
    from loads.commercial import Commercial

    pd.options.display.max_columns = None
    pd.options.display.width = None

    states = sorted(Counties(use_index="SYSTEM").loc["WECC"]["ST"].unique())
    result = []
    for state in states:
        print("Processing",state,end="...",flush=True)
        result.append(Calibrate.state(state).unstack())
        print("ok")
    print(pd.concat(result))