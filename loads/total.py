"""Total load aggregation module

The total load module computes the expected sum of the residential,
commercial, industrial and agricultural loads at the county level for the
specified year.

Note that calibration requires that the total load and DG for each county in a
state is computed first before the load for a specified county can be
calculated. This can take some time if it has not been done before and is not
in the loads cache.

Data Flow
---------

The county-level total and net loads are calculated as follows:

```mermaid
flowchart TD

    OpenEI ---> Industrial
    OpenEI ---> Agricultural
    OpenEI ---> Transportation

    Energy --------> Calibration

    EIA --> Energy
    NREL --> Weather

    Calibration --> Load
    Calibration --> DG

    Residential --> TSGAM
    Commercial --> TSGAM

    NREL --> RESstock
    NREL --> COMstock

    RESstock --> Residential
    COMstock --> Commercial

    Weather --> Sample[Sample/Predict]
    Weather ----> TSGAM
    Weather --> DG

    TSGAM --> Fit(Fit)

    Fit --> Estimator

    Estimator --> Sample

    Sample --> Calibration

    Industrial -------> Load
    Agricultural -------> Load
    Transportation -------> Load

    Load --> Net
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

Known Issues
------------

1. Log-load is regarded as a better model, however the current implementation
does not exclude zeros from training or learn when zero should be predicted.
(See `ISSUE 1` in code below.)

2. The current total from the main run is a sample, not a prediction, or a
percentile of K samples. (See `ISSUE 2` in code below.)
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
    """Total load aggregation class implementation

    Columns
    -------

      - `elec_residential_MW`: total residential building loads

      - `elec_commercial_MW`: total commercial building loads

      - `elec_industrial_MW`: total industrial loads

      - `elec_agricultural_MW`: total agricultural loads

      - `elec_total_MW`: total loads

      - `elec_dg_MW`: total distributed generation

      - `elec_net_MW`: total net loads

      - `temperature_degF`: dry-bulb temperature used to predict loads

      - `global_Wpms`: global horizontal irradiance used to predict DG

      - `direct_Wpms`: direct normal irradiance used to to predict DG

      - `diffuse_Wpms`: global diffuse irradiance used to predict DG

    Caveats
    -------

      - Only direct normal and global diffuse irradiance are currently used to
        predict DG using a simple least-squares fit

      - Large loads as defined by NERC (e.g., data centers) are not included.

      - Transportation loads are current set to 0 because they are less than
        1% of total electric loads.
    """

    CACHEDIR = None
    """Cache folder"""

    DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S%z"
    """Date/time format to use"""

    cache = {}

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

    EXOGENOUS_VARIABLES = {
        "elec_residential_MW": ["temperature_degF"],
        "elec_commercial_MW": ["temperature_degF"],
        "elec_total_MW": ["temperature_degF"],
        "elec_dg_MW": ["diffuse_Wpms","direct_Wpms"],
        "elec_net_MW": ["temperature_degF","diffuse_Wpms","direct_Wpms"],
        "nonelec_residential_MW": ["temperature_degF"],
        "nonelec_commercial_MW": ["temperature_degF"],
        "nonelec_total_MW": ["temperature_degF"],
    }
    """Solar DG model independent variables to use"""

    INDUSTRY_LOADSHAPE = None
    AGRICULTURE_LOADSHAPE = None
    TRANSPORTATION_LOADSHAPE = None
    """Default sector loadshapes (None is a flat load)"""

    def __init__(self,
        state:str,
        county:str,
        *,
        Y:str="elec_total_MW",
        X:str=None,
        date_range:pd.DatetimeIndex=None,
        samples:int=None,
        percentile:float=96,
        holdout:pd.DatetimeIndex|None=None,
        refresh:bool=False,
        ):
        """Total load class constructor

        Arguments
        ---------

          - `state`: state for which to aggregate loads

          - `county`: county for which to aggregate loads

          - `start`: start of date/time range

          - `end`: end of date/time range

          - `freq`: date/time range interval

          - `samples`: number of AR samples to generation (`0` predicts, `1`
            samples, `>1` samples with percentile, `None` training only if
            year is training year otherwise predicts)

          - `holdout`: index of records to hold out of training for testing

          - `refresh`: refresh cache data
        """

        # identify location of cached results
        if self.CACHEDIR:
            Cache.CACHEDIR = self.CACHEDIR

        # choose sampling method
        assert samples is None or isinstance(samples,int), f"{sample=} is not valid"
        if samples is None:

            # no sampling gets training data (also ignores date range)
            return super().__init__(Total._get_training(state,county,X,Y,refresh))

        # set default exogenous variable(s)
        if X is None:
            X = self.EXOGENOUS_VARIABLES[Y]

        # sampling requires a valid date range
        assert isinstance(date_range,pd.DatetimeIndex), f"{date_range=} must be Pandas DatetimeIndex"
        if samples == 0:

            # zero samples gets prediction without sampling
            return super().__init__(Total._get_predict(state,county,date_range,X,Y,refresh))

        if samples == 1:

            # one sample does not use percentile
            return super().__init__(Total._get_sample(state,county,date_range,X,Y,refresh))

        if samples > 1:

            assert 0<=percentile<=1, f"{percentile=} must be between 0 and 1"

            # multiple samples uses percentile
            return super().__init__(Total._get_percentile(state,county,date_range,X,Y,samples,percentile,refresh))

        raise ValueError(f"{samples=} must be a non-negative integer, infinity, or None")

    @classmethod
    def _get_training(cls,
        state:str,
        county:str,
        X:list[str],
        Y:str,
        refresh:bool=False,
        ):
        """Get the training data only"""

        # identify location of cached results
        nonelec = Y.startswith("nonelec_")
        source = "nonelec" if nonelec else "elec"
        cache = Cache(package="loads",version=0,path=[state,county,f"T_{source}_1h_training.csv.gz"])

        # load refresh from cache
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

        # no results available from cache
        if data is None:

            # get training weather data
            data = Weather(state,county)

            # DG only possible with electric loads
            if not nonelec:
                data["elec_dg_MW"] = 0.0

            # get building data
            for sector,dataset in {
                    "residential":Residential,
                    "commercial":Commercial,
                    }.items():

                loaddata = dataset(state,county)
                data[f"{source}_{sector}_MW"] = loaddata[f"{source}_total_MW"]
                if not nonelec:
                    data["elec_dg_MW"] += loaddata[f"{source}_dg_MW"]

            # make flat loadshape
            loadshape = pd.DataFrame(
                data=np.ones(len(data)),
                index=data.index,
                )

            # get industrial loads
            data[f"{source}_industrial_MW"] = Industry(
                state,
                county,
                loadshape if cls.INDUSTRY_LOADSHAPE is None else cls.INDUSTRY_LOADSHAPE,
                )[f"{source}_{'total' if nonelec else 'net'}_MW"]

            # get agricultural loads
            data[f"{source}_agricultural_MW"] = Agriculture(
                state,
                county,
                loadshape if cls.AGRICULTURE_LOADSHAPE is None else cls.AGRICULTURE_LOADSHAPE,
                )[f"{source}_{'total' if nonelec else 'net'}_MW"]
            
            # set transportation to zero until data is available
            data[f"{source}_transportation_MW"] = 0.0
            
            # finalize total load
            data[f"{source}_total_MW"] = data[[x for x in data.columns if x.endswith("_MW")]].sum(axis=1)
            data[f"{source}_net_MW"] = data[f"{source}_total_MW"]

            # finalize net load
            if not nonelec:
                data[f"elec_net_MW"] += data["elec_dg_MW"]

            # save cache
            data.to_csv(cache.pathname,
                index=True,
                header=True,
                compression="gzip" if cache.pathname.endswith(".gz") else None,
                )

        return data

    @classmethod
    def _get_weather(cls,
        state:str,
        county:str,
        date_range:pd.DatetimeIndex,
        ):
        """Get weather data for a date/time range"""
        data = []
        for year in set(date_range.year):
            data.append(Weather(state,county,year))
        data = pd.concat(data)
        return data.loc[date_range]

    @classmethod
    def _get_estimator(cls,
        state:str,
        county:str,
        X:list[str],
        Y:str,
        refresh:bool=False,
        ) -> TsgamEstimator:
        """Get estimator"""

        # get cache name
        cache = (state,county,"|".join(X),Y)

        # return estimator if cache active and found in cache
        if not cls.cache is None and cache in cls.cache:
        
            return cls.cache[cache]

        # get training data
        training = cls._get_training(state,county,X,Y,refresh)

        # create estimator
        estimator = TsgamEstimator(config=cls.TSGAM_CONFIG)

        # fit training data
        estimator.fit(training[X],np.log(training[Y].values))

        # save estimator
        if not cls.cache is None:
            cls.cache[cache] = estimator

        return estimator

    @classmethod
    def _get_predict(cls,
        state:str,
        county:str,
        date_range:pd.DatetimeIndex,
        X:str,
        Y:str,
        refresh:bool=False,
        ) -> pd.DataFrame:
        """Get the prediction for the specified date range"""
        
        # get estimator
        estimator = cls._get_estimator(state,county,X,Y)

        # get the exogenous data
        data = cls._get_weather(state,county,date_range)[X]

        # get the prediction
        data[Y] = np.exp(estimator.predict(data[X]))

        return data

    @classmethod
    def _get_sample(cls,
        state:str,
        county:str,
        date_range:pd.DatetimeIndex,
        X:str,
        Y:str,
        refresh:bool=False,
        ) -> pd.DataFrame:
        """Get the prediction for the specified date range"""
        
        # get estimator
        estimator = cls._get_estimator(state,county,X,Y)

        # get the exogenous data
        data = cls._get_weather(state,county,date_range)[X]

        # get the samples
        data[Y] = np.exp(estimator.sample(data[X])[0])

        return data

    @classmethod
    def test(cls,
        state:str,
        county:str,
        holdout:pd.DatetimeIndex,
        X:str=["temperature_degF"],
        Y:str="elec_total_MW",
        ) -> pd.DataFrame:
        """Perform a hold-out test on the training data

        Arguments
        ---------

          - `state`: state in which county is located

          - `county`: county to draw data from

          - `holdout`: index of hold rows

          - `X`: X columns in `loads.total.Total` to use as exogenous variables

          - `Y`: Y column in `loads.total.Total` to fit

        Returns
        -------

          - `pd.DataFrame`: the X and Y data frame augmented with `predict` and `sample`
        """

        # get original data
        data = cls._get_training(state,county,X,Y)[X+[Y]].copy()
        daterange = data.index

        # remove holdout data from training
        training = data.copy()
        training.loc[holdout,Y] = float('nan')

        # remove lag windows from head and tail of training data
        # headlag = 0
        # taillag = 0
        # for config in [x for x in self.TSGAM_CONFIG.exog_config if hasattr(x,"lags")]:
        #     headlag = -min(min(config.lags)+1,headlag)
        #     taillag = -max(max(config.lags),taillag)
        # training.loc[:training.index[headlag],X] = float('nan')
        # training.loc[training.index[taillag]:,X] = float('nan')
        training.dropna(inplace=True)

        # get estimator
        estimator = TsgamEstimator(config=cls.TSGAM_CONFIG)
        estimator.fit(training[X],np.log(training[Y].values))

        # get holdout data for tests
        test = data.loc[holdout,X+[Y]]

        # get the test data
        data.loc[test.index,"predict"] = np.exp(estimator.predict(test[X]))
        data.loc[test.index,"sample"] = np.exp(estimator.sample(test[X]))[0]

        # return data
        return data

    @classmethod
    def _clear_cache(cls):
        """Clear the estimator cache"""
        cls.cache = { 
            "scale": {},
            "load": {},
            "solar": {},
        }


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
    import matplotlib.pyplot as plt
    
    pd.options.display.max_columns = None
    pd.options.display.width = None

    refresh = "--refresh" in sys.argv
    debug = "--debug" in sys.argv

    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    
    test_range = pd.date_range(
        start="2018-01-01 00:00:00+0000",
        end="2018-12-31 23:59:59+0000",
        freq="1h",
        )
    holdout = test_range[test_range.month != (test_range + dt.timedelta(days=7)).month]

    full_range = pd.date_range(
        start="2018-01-01 00:00:00+0000",
        end="2022-12-31 23:59:59+0000",
        freq="1h",
        )

    for state,county in Counties(use_index="SYSTEM",selection="WECC")[["ST","COUNTY"]].values:

        Total._clear_cache()

        result = Total.test(state,county,holdout,Y="elec_total_MW")
        residual = result["predict"] - result["elec_total_MW"]
        RMSE = np.sqrt(np.mean(residual**2))
        RMPE = RMSE/result["elec_total_MW"].mean()*100
        print(f"{county} {state} elec_total_MW {RMPE=:.1f}%",flush=True)

        result.rename({"elec_total_MW":"actual"},axis=1,inplace=True)
        result.predict = Total(state,county,date_range=test_range,samples=0)["elec_total_MW"]
        result.sample = Total(state,county,date_range=test_range,samples=1)["elec_total_MW"]

        training = result["actual"]
        result = Total(state,county,date_range=full_range,samples=0)
        result.rename({"elec_total_MW":"predict"},axis=1,inplace=True)
        result["sample"] = Total(state,county,date_range=full_range,samples=1)["elec_total_MW"]
        result["actual"] = Total(state,county,Y="elec_total_MW")["elec_total_MW"]
        print(result,flush=True)

        result[["predict","sample","actual"]].plot(
            figsize=(20,10),
            title=f"{county} {state} elec_total_MW",
            grid=True,
            legend=True,
            xlabel="Date/Time",
            ylabel="Power (MW)",
            )
        plt.show()

        # sample = Total(state,county,
        #     start="2019-01-01 00:00:00+0000",
        #     end="2022-12-31 23:59:59+0000",
        #     samples=1,
        #     percentile=0.5,
        #     )
        # print(sample)

        # samples = Total(state,county,
        #     start="2019-01-01 00:00:00+0000",
        #     end="2022-12-31 23:59:59+0000",
        #     samples=100,
        #     percentile=0.5,
        #     )
        # print(samples)

        # samples = Total(state,county,
        #     start="2019-01-01 00:00:00+0000",
        #     end="2022-12-31 23:59:59+0000",
        #     samples=np.inf,
        #     percentile=0.5,
        #     )
        # print(samples)

        #     try:
        #         # TODO
        #         _logger.info(f"{state} {county} {year} ok")
        #     except Exception as err:
        #         (_logger.exception if debug else _logger.error)(f"{state} {county} {year} {err}")
