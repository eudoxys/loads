"""Total load aggregation module

The total load module computes the expected sum of the residential,
commercial, industrial and agricultural loads at the county level for the
specified year.

Note that calibration requires that the total load for each county in a state
is computed first before the load for a specified county can be calculated.
This can take some time if it has not been done before and is not in the loads
cache.

Data Flow
---------

The county-level total and net loads are calculated as follows:

```mermaid
flowchart TD

    OpenEI --> Industrial
    OpenEI --> Agricultural
    OpenEI --> Transportation
    EIA --> Energy
    EIA --> Peak

    Weather --> DG
    Weather --> Sample[Sample/Predict]
    Weather ----> TSGAM

    Energy --> eCalibration[Energy Calibration]
    Peak --> pCalibration[Peak Calibration]

    NREL --> Solar
    NREL --> Weather

    Solar --> DG

    eCalibration --> TSGAM

    Residential --> eCalibration
    Commercial --> eCalibration

    NREL --> RESstock
    NREL --> COMstock

    RESstock --> Residential
    COMstock --> Commercial

    TSGAM --> Fit(Fit)

    Fit --> Estimator

    %% Weather --> Predict

    %% Estimator --> Predict
    Estimator --> Sample

    %% Predict --> Total
    Sample --> Total

    Industrial --> pCalibration
    pCalibration --> Total
    Agricultural -------> Total
    Transportation -------> Total

    Total --> Net
    DG --> Net
```

Example
-------

To compute the total load in 2020 for Alameda County CA use the following

    from loads import Total
    Total("CA","Alameda",2020)

which outputs

                               elec_residential_MW  elec_commercial_MW  elec_industrial_MW  elec_agricultural_MW  elec_transportation_MW  elec_total_MW  elec_net_MW  elec_dg_MW  temperature_degF  global_Wpms  direct_Wpms  diffuse_Wpms
    timestamp                                                                                                                                                                                                                             
    2020-01-01 00:00:00+00:00             1000.677             988.157             223.618                 6.901                     0.0       2219.353     2219.353        -0.0              50.9         37.0         40.0          34.0
    2020-01-01 01:00:00+00:00              857.849             850.925             223.618                 6.901                     0.0       1939.294     1939.294        -0.0              49.5          0.0          0.0           0.0
    2020-01-01 02:00:00+00:00              675.618             715.667             223.618                 6.901                     0.0       1621.805     1621.805        -0.0              48.9          0.0          0.0           0.0
    2020-01-01 03:00:00+00:00              523.432             589.093             223.618                 6.901                     0.0       1343.044     1343.044        -0.0              48.7          0.0          0.0           0.0
    2020-01-01 04:00:00+00:00              492.401             597.660             223.618                 6.901                     0.0       1320.580     1320.580        -0.0              48.0          0.0          0.0           0.0
    ...                                        ...                 ...                 ...                   ...                     ...            ...          ...         ...               ...          ...          ...           ...
    2020-12-31 19:00:00+00:00              425.438             659.111             223.618                 6.901                     0.0       1315.069     1315.069        -0.0              54.9        497.0        891.0          70.0
    2020-12-31 20:00:00+00:00              397.054             640.492             223.618                 6.901                     0.0       1268.065     1268.065        -0.0              56.7        506.0        890.0          72.0
    2020-12-31 21:00:00+00:00              473.943             712.390             223.618                 6.901                     0.0       1416.852     1416.852        -0.0              57.4        456.0        859.0          71.0
    2020-12-31 22:00:00+00:00              584.162             764.285             223.618                 6.901                     0.0       1578.966     1578.966        -0.0              57.2        351.0        797.0          63.0
    2020-12-31 23:00:00+00:00              738.641             861.597             223.618                 6.901                     0.0       1830.758     1830.758        -0.0              53.6        207.0        668.0          51.0

    [8784 rows x 12 columns]
"""

import datetime as dt
import logging

import pandas as pd
import numpy as np

from fips import Counties
from weather import Weather
from cache import Cache
from loads.residential import Residential
from loads.commercial import Commercial
from loads.industry import Industry
from loads.agriculture import Agriculture
from loads.calibrate import Calibrate
from loads.tsgam_estimator import (
    TsgamEstimatorConfig, 
    TsgamMultiHarmonicConfig,
    TsgamSplineConfig,
    TsgamArConfig,
    TsgamSolverConfig,
    TsgamEstimator,
    )
from loads.solar_estimator import SolarEstimator

_logger = logging.getLogger(__file__)

class Total(pd.DataFrame):
    """Total load aggregation class implementation"""

    CACHEDIR = None
    """Cache folder"""

    DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S%z"
    """Date/time format to use"""

    cache = {
        "scale": {},
        "load": {},
        "solar": {},
    }

    PRECISION = 3
    """Precision of predicted/sampled loads"""

    TSGAM_CONFIG = TsgamEstimatorConfig(
        multi_harmonic_config=TsgamMultiHarmonicConfig(
            num_harmonics=[6, 4, 3],
            periods=[365.2425 * 24, 7 * 24, 24]
        ),
        exog_config=[TsgamSplineConfig(
                    knots=[],  # Empty list means knots will be auto-generated from data
                    n_knots=10,  # Number of knots to generate
                    lags=[-3, -2, -1, 0, 1, 2, 3],
                    reg_weight=1e-4,  # Regularization weight for coefficients
                    diff_reg_weight=1.0  # Regularization weight for differences between lags
                )],
        ar_config=TsgamArConfig(
            lags = list(range(1,36))
            ),
        solver_config=TsgamSolverConfig(
            solver='CLARABEL',
            verbose=False
        ),
        random_state=None,
        debug=False
    )
    """Time-series General Additive Model estimator configuration"""

    def __init__(self,
        state:str,
        county:str,
        year:int|str,
        freq:str="1h",
        samples:int=1,
        percentile:float=95,
        nonelec:bool=False,
        refresh:bool=False,
        ):
        """Total load class constructor

        Arguments
        ---------

          - `state`: state for which to aggregate loads

          - `county`: county for which to aggregate loads

          - `year`: target year

          - `samples`: number of AR samples to generation (0=predict onlyl)

          - `nonelec`: use non-electric total load

          - `refresh`: refresh cache data
        """

        if isinstance(year,str):
            year = int(year)
        source = "nonelec" if nonelec else "elec"

        if self.CACHEDIR:
            Cache.CACHEDIR = self.CACHEDIR
        if samples and samples > 1:
            cache = Cache(package="loads",version=0,path=[state,county,year,f"T_{source}_{freq}_{samples}_{percentile}.csv.gz"])
        else:
            cache = Cache(package="loads",version=0,path=[state,county,year,f"T_{source}_{freq}.csv.gz"])

        # load data from cache
        if cache.exists() and not refresh:

            try:
                data = pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0])
                _logger.debug(f"{cache=} ok")
            except Exception as err:
                data = None
                cache.delete()
                _logger.error(f"{cache=} {err}")

        else:
            data = None
            _logger.debug(f"{cache=} (re)generation required")

        if data is None:

            # get residential and commercial loads
            # TODO: change to log(MW), need to address zeros
            weather = Weather(state,county)
            if nonelec:
                data = Weather(state,county,year)[["temperature_degF"]]
            else:
                data = Weather(state,county,year)[["temperature_degF","global_Wpms","direct_Wpms","diffuse_Wpms"]]

            if not nonelec:
                data["elec_dg_MW"] = 0.0
            for sector,dataset in {
                    "residential":Residential,
                    "commercial":Commercial,
                    }.items():

                # get previously constructor estimators 
                if (state,county,sector) in self.cache["load"] and (state,county,sector) in self.cache["solar"]:
                    estimator = self.cache["load"][(state,county,sector)]
                    if not nonelec:
                        solar = self.cache["solar"][(state,county,sector)]
                else:

                    # create a new estimator
                    estimator = TsgamEstimator(config=self.TSGAM_CONFIG)
                    if not nonelec:
                        solar = SolarEstimator()

                    # create a new calibrator
                    calibrate = Calibrate.state(state,year)

                    # gather the training data for this state, county, and sector
                    loaddata = dataset(
                        state,
                        county,
                        calibrate=calibrate.loc[sector[0].upper()].values[0],
                        )
                    training = pd.concat([loaddata,weather],axis=1)

                    # fit the estimators (with nans as zeros)
                    estimator.fit(
                        training[["temperature_degF"]],
                        training[f"{source}_total_MW"].fillna(0).values,
                        )
                    if not estimator.problem_.status in ["optimal", "optimal_inaccurate"]:
                        raise RuntimeError(f"unable to fit: {estimate.problem_.status}")
                    
                    if not nonelec:
                        solar.fit(
                            training[["diffuse_Wpms","direct_Wpms"]],
                            training["elec_dg_MW"].fillna(0).abs().values,
                            )

                    # save the estimator for future use, e.g., different years
                    self.cache["load"][(state,county,sector)] = estimator
                    if not nonelec:
                        self.cache["solar"][(state,county,sector)] = solar

                # no sampling requested
                if not samples:
                    data[f"{source}_{sector}_MW"] = estimator.predict(data)
                    if not nonelec:
                        data["elec_dg_MW"] -= solar.predict(data[["diffuse_Wpms","direct_Wpms"]].fillna(0).values)

                # one sample requested
                elif samples == 1:
                    data[f"{source}_{sector}_MW"] = estimator.sample(data,1)[0]
                    if not nonelec:
                        data["elec_dg_MW"] -= solar.sample(data,1)[0]

                # percentile of multiple samples requested (this can be slow)
                else:
                    data[f"{source}_{sector}_MW"] = np.percentile(estimator.sample(data,samples),percentile)

            # TODO: calibrate industrial loadshape to match peak
            loadshape = pd.DataFrame(
                data=np.ones(len(data)),
                index=data.index,
                )
            data[f"{source}_industrial_MW"] = Industry(state,county,loadshape)[f"{source}_{'total' if nonelec else 'net'}_MW"]

            # get agricultural loads and set transportation to zero            
            data[f"{source}_agricultural_MW"] = Agriculture(state,county,loadshape)[f"{source}_{'total' if nonelec else 'net'}_MW"]
            data[f"{source}_transportation_MW"] = 0.0
            
            
            data[f"{source}_total_MW"] = data[[x for x in data.columns if x.endswith("_MW")]].sum(axis=1)
            data[f"{source}_net_MW"] = data[f"{source}_total_MW"]

            # TODO: train DG based on solar data
            if not nonelec:
                data[f"elec_net_MW"] += data["elec_dg_MW"]
            
            data.to_csv(cache.pathname,
                index=True,
                header=True,
                compression="gzip" if cache.pathname.endswith(".gz") else None,
                )

        super().__init__(data[
            [x for x in data.columns if x.endswith("_MW")] +
            [x for x in data.columns if not x.endswith("_MW")]
            ].round(self.PRECISION))

    @classmethod
    def makeargs(cls,**kwargs):
        """@private Return dict of accepted kwargs by this class constructor"""
        return {x:y for x,y in kwargs.items()
            if x in cls.__init__.__annotations__}

if __name__ == "__main__":
    """Main script

    The main script refreshes the cache with debugging enabled.
    """

    import sys
    
    pd.options.display.max_columns = None
    pd.options.display.width = None

    refresh = "--refresh" in sys.argv
    debug = "--debug" in sys.argv

    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    
    for state,county in Counties(use_index="SYSTEM",selection="WECC")[["ST","COUNTY"]].values:
        for year in range(2018,2023):
            try:
                Total(state,county,year,nonelec=False,refresh=refresh,samples=None)
                _logger.info(f"{state} {county} {year} ok")
            except Exception as err:
                (_logger.exception if debug else _logger.error)(f"{state} {county} {year} {err}")
