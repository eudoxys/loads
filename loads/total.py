"""Total load aggregation module

The total load aggregate module computes the sum of the residential,
commercial, industrial and agricultural loads at the county level in each
state.

Example
-------

To compute the total load in 2020 for Alameda County CA use the following

    from loads import Total
    Total("CA","Alameda",2020)

which outputs

                               elec_baseload_MW  elec_cooling_MW  elec_dg_MW  elec_heating_MW  ...  humidity_pc  global_Wpms  direct_Wpms  diffuse_Wpms
    timestamp                                                                                  ...                                                     
    2020-01-01 00:00:00+00:00        875.936758        12.275047   -1.308691       119.031976  ...  7441.843208  1613.893708     0.000000   1613.893708
    2020-01-01 01:00:00+00:00        966.255125        11.165026    0.000000       125.994575  ...  7190.793076    89.660762   224.151904     89.660762
    2020-01-01 02:00:00+00:00        985.739523        10.193724    0.000000       140.598172  ...  7136.996619     0.000000     0.000000      0.000000
    2020-01-01 03:00:00+00:00        972.520338         9.490080    0.000000       148.451541  ...  6195.558622     0.000000     0.000000      0.000000
    2020-01-01 04:00:00+00:00        931.999704         9.656636    0.000000       142.825713  ...  5962.440642     0.000000     0.000000      0.000000
    ...                                     ...              ...         ...              ...  ...          ...          ...          ...           ...
    2020-12-31 19:00:00+00:00        947.877004        12.888278   -2.859527       178.552351  ...  7450.809284  3227.787415     0.000000   3227.787415
    2020-12-31 20:00:00+00:00        962.784910        12.836871   -4.207248       183.036471  ...  8338.450823  4617.529219     0.000000   4617.529219
    2020-12-31 21:00:00+00:00        934.669867        12.684631   -3.040338       177.558581  ...  8338.450823  3407.108939     0.000000   3407.108939
    2020-12-31 22:00:00+00:00        901.014894        12.377845   -3.209998       174.477905  ...  8338.450823  3586.430462     0.000000   3586.430462
    2020-12-31 23:00:00+00:00        851.636725        11.707962   -2.954313       184.026453  ...  8966.076154  3317.448177     0.000000   3317.448177

    [8784 rows x 15 columns]

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
from tsgam_estimator import (
    TsgamEstimatorConfig, 
    TsgamMultiHarmonicConfig,
    TsgamSplineConfig,
    TsgamArConfig,
    TsgamSolverConfig,
    TsgamEstimator,
    )

_logger = logging.getLogger(__file__)

class Total(pd.DataFrame):
    """Total load aggregation class implementation"""

    CACHEDIR = None
    """Cache folder"""

    DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S%z"
    """Date/time format to use"""

    cache = {
        "scale": {},
        "estimator": {}
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
        column = "nonelec_total_MW" if nonelec else "elec_total_MW"

        if self.CACHEDIR:
            Cache.CACHEDIR = self.CACHEDIR
        cache = Cache(package="loads",version=0,path=[state,county,f"R_{column}_{freq}_{samples}_{percentile}.csv.gz"])

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
            train = Weather(state,county)["temperature_degF"].to_frame()
            data = Weather(state,county,year)["temperature_degF"].to_frame()
            for sector,dataset in {
                    "residential_MW":Residential,
                    "commercial_MW":Commercial,
                    }.items():
                if (state,county,sector) in self.cache["estimator"]:
                    estimator = self.cache["estimator"][(state,county,sector)]
                else:
                    estimator = TsgamEstimator(config=self.TSGAM_CONFIG)
                    train[sector] = dataset(state,county)[column]
                    estimator.fit(train.temperature_degF.to_frame(),train[sector].values)
                    if not estimator.problem_.status in ["optimal", "optimal_inaccurate"]:
                        raise RuntimeError(f"unable to fit: {estimate.problem_.status}")
                    self.cache["estimator"][(state,county,sector)] = estimator
                if not samples:
                    data[sector] = estimator.predict(data)
                elif samples == 1:
                    data[sector] = estimator.sample(data,1)[0]
                else:
                    data[sector] = np.percentile(estimator.sample(data,samples),percentile)

            # TODO: calibrate industrial loadshape to match peak
            loadshape = pd.DataFrame(
                data=np.ones(len(data)),
                index=data.index,
                )
            data["industrial_MW"] = Industry(state,county,loadshape)[column]

            # get agricultural loads and set transportation to zero            
            data["agricultural_MW"] = Agriculture(state,county,loadshape)[column]
            data["transportation_MW"] = 0.0
            
            # TODO: train DG based on solar data
            data["dg_MW"] = -0.0 # TODO
            
            data["total_MW"] = data[[x for x in data.columns if x.endswith("_MW")]].sum(axis=1)
            data["net_MW"] = data["total_MW"] + data["dg_MW"]
            
            data.to_csv(cache.pathname,
                index=True,
                header=True,
                compression="gzip" if cache.pathname.endswith(".gz") else None,
                )

        super().__init__(data.round(self.PRECISION))

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
                result = Total(state,county,year,refresh=refresh)
                _logger.debug(f"{state} {county} ok")
            except Exception as err:
                (_logger.exception if debug else _logger.error)(f"{state} {county} {year} {err}")
                raise
