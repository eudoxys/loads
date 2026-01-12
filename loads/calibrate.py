r"""Load calibration module

The `calibration` module is used to rescale loads to match know energy
consumptions over a specified time period.  The rescaling such that
for each column of the data table with a name ending in `'_MW'`

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
        energy:float,
        start:dt.datetime|str=None,
        end:dt.datetime|str=None,
        ):
        """Construct a calibrated load data frame

        Arguments
        ---------

          - `load`: old uncalibrated load data

          - `energy`: new energy consumption to calibrate load with

          - `start`: start date of new energy consumption

          - `end`: end date of new energy consumption
        """

        data = load.copy().reset_index().set_index(self.DATETIME_INDEX)
        
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

        super().__init__(data)

if __name__ == '__main__':
    
    from loads.residential import Residential

    pd.options.display.max_columns = None
    pd.options.display.width = None

    test = Residential("CA","Alameda")
    old_energy = integrate(test)
    new_energy = old_energy * 2
    result = Calibrate(test,new_energy)
    assert ((result-2*test).sum()==0).all(), f"Test failed!"
