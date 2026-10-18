"""Total load aggregation module

The total load module computes the sum of the residential, commercial,
industrial and agricultural loads at the county level for the 2018 training
year, and uses a TSGAM estimator trained on those loads and the county's 2018
weather to predict or sample a load column for any date range with weather
data.

Data Flow
---------

The county-level total and net loads are calculated as follows:

```mermaid
flowchart TD

    NLR --> RESstock --> Residential
    NLR --> COMstock --> Commercial
    NLR --> Industrial
    NLR --> Agricultural
    Transportation[Transportation = 0]
    NSRDB --> Weather

    Residential --> Loads[2018 training data]
    Commercial --> Loads
    Industrial --> Loads
    Agricultural --> Loads
    Transportation --> Loads
    Residential -->|pv| DG[elec_dg_MW]
    Commercial -->|pv| DG
    DG --> Loads
    Weather -->|2018| Loads

    subgraph TSGAM Estimator
        Fit --> Estimator
        Estimator --> Sample[Sample/Predict]
    end

    Loads -->|X, Y| Fit
    Weather -->|date_range| Sample
    Sample --> Y[Y column for date_range]
```

In the training data `elec_total_MW` is the sum of the sector loads and
`elec_net_MW = elec_total_MW + elec_dg_MW`, where `elec_dg_MW` is the
(negative) rooftop PV output of the residential and commercial building
stock.

Examples
--------

To get the 2018 training data for Alameda County CA, i.e., the sector loads,
total, distributed generation, net load, and weather, use

    from loads import Total
    Total("CA","Alameda")

which returns 8760 hourly rows with the weather columns and the columns
`elec_dg_MW`, `elec_residential_MW`, `elec_commercial_MW`,
`elec_industrial_MW`, `elec_agricultural_MW`, `elec_transportation_MW`,
`elec_total_MW`, and `elec_net_MW`.

To predict the total load in 2020 for Alameda County CA use

    import pandas as pd
    date_range = pd.date_range("2020-01-01 00:00:00+00:00",
        "2020-12-31 23:00:00+00:00",freq="1h")
    Total("CA","Alameda",date_range=date_range,samples=0)

which returns 8784 hourly rows with the exogenous variables
`temperature_degF` and `humidity_pc`, and the predicted `elec_total_MW`.
The first and last 3 hours of the prediction are NaN because of the
exogenous variable lags in `Total.TSGAM_CONFIG`.

To get the 95th percentile of 100 autoregressive samples of the distributed
generation use

    Total("CA","Alameda",Y="elec_dg_MW",date_range=date_range,
        samples=100,percentile=95)

Use `percentile=None` to get all the samples in columns `sample_0`,
`sample_1`, etc.

Known Issues
------------

1. Log-load is regarded as a better model, however loads are currently fitted
in the linear domain (see `Total.TRANSFORMATIONS`) because the implementation
does not exclude zeros from training or learn when zero should be predicted.

2. The `dg` and `holdout` constructor arguments are accepted but not used.
Use `Total.test` to perform a holdout test.

3. The main script of this module saves its results to the gitignored
`tests/` folder.
"""

import datetime as dt
import logging

import pandas as pd
import numpy as np

from tsgam_estimator import (
    TsgamEstimatorConfig,
    TsgamMultiPeriodicConfig,
    TsgamSplineConfig,
    TsgamArConfig,
    TsgamSolverConfig,
    TsgamEstimator,
    )

from fips import Counties
from weather import Weather
from cache import Cache
from loads.residential import Residential
from loads.commercial import Commercial
from loads.industry import Industry
from loads.agriculture import Agriculture
from loads.dgen import DG

_logger = logging.getLogger(__file__)

class Total(pd.DataFrame):
    """Total load aggregation class implementation

    Columns
    -------

    The training data (`samples=None`) contains the following columns:

      - `elec_residential_MW`: total residential building loads

      - `elec_commercial_MW`: total commercial building loads

      - `elec_industrial_MW`: total industrial loads

      - `elec_agricultural_MW`: total agricultural loads

      - `elec_transportation_MW`: total transportation loads (always 0)

      - `elec_total_MW`: total loads (sum of the sector loads)

      - `elec_dg_MW`: total distributed generation (never positive)

      - `elec_net_MW`: total net loads (`elec_total_MW + elec_dg_MW`)

      - `temperature_degF`: dry-bulb temperature used to predict loads

      - `humidity_pc`: relative humidity used to predict loads

      - `global_Wpms`: global horizontal irradiance

      - `direct_Wpms`: direct normal irradiance used to predict DG

      - `diffuse_Wpms`: diffuse horizontal irradiance used to predict DG

    plus any other columns provided by `weather.Weather`. When `Y` starts with
    `nonelec_`, the training data contains the `nonelec_` sector, total, and
    net columns instead and has no DG column.

    Predictions and samples (`samples>=0`) contain the `X` columns and the `Y`
    column only (or `sample_0`, `sample_1`, etc. when `samples>1` and
    `percentile=None`).

    Caveats
    -------

      - Only direct normal and diffuse irradiance are used to predict DG (see
        `Total.EXOGENOUS_VARIABLES`).

      - Large loads as defined by NERC (e.g., data centers) are not included.

      - Transportation loads are currently set to 0 because they are less than
        1% of total electric loads.
    """

    CACHEDIR = None
    """Cache folder"""

    DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S%z"
    """Date/time format to use"""

    cache = {}
    """Estimator cache"""

    PRECISION = 3
    """Precision of predicted/sampled loads"""

    TSGAM_CONFIG = TsgamEstimatorConfig(
        multi_periodic_config=TsgamMultiPeriodicConfig(
            num_harmonics=[4,4,12],
            periods=[365.2425 * 24, 7 * 24, 24]
        ),
        exog_config=[TsgamSplineConfig(
                    knots=[],  # Empty list means knots will be auto-generated from data
                    n_knots=7,  # Number of knots to generate
                    lags=[-3, -2, -1, 0, 1, 2, 3],
                    reg_weight=1e-4,  # Regularization weight for coefficients
                    diff_reg_weight=1.0  # Regularization weight for differences between lags
                )],
        ar_config=TsgamArConfig(
            lags = list(range(1,10))
            ),
        solver_config=TsgamSolverConfig(
            solver='CLARABEL',
            # solver='HIGHS',
            verbose=False
        ),
        random_state=None,
        debug=False
    )
    """Time-series General Additive Model estimator configuration"""

    EXOGENOUS_VARIABLES = {
        "elec_residential_MW": ["temperature_degF","humidity_pc"],
        "elec_commercial_MW": ["temperature_degF","humidity_pc"],
        "elec_total_MW": ["temperature_degF","humidity_pc"],
        "elec_dg_MW": ["direct_Wpms","diffuse_Wpms"],
        "nonelec_residential_MW": ["temperature_degF","humidity_pc"],
        "nonelec_commercial_MW": ["temperature_degF","humidity_pc"],
        "nonelec_total_MW": ["temperature_degF","humidity_pc"],
    }
    """Exogenous variable to use for prediction variables

    Notes
    -----

    1. Based on experience `elec_dg_MW` uses only diffuse and direct solar at this time.
    """

    TRANSFORMATIONS = { # pre/post processors of Y values
        "elec_residential_MW" : (None,None),
        "elec_commercial_MW" : (None,None),
        "elec_total_MW" : (None,None),
        "elec_net_MW" : (None,None),
        "nonelec_residential_MW" : (None,None),
        "nonelec_commercial_MW" : (None,None),
        "nonelec_total_MW" : (None,None),
        "elec_dg_MW": (np.negative,np.negative),
        # Notes:
        # 1. elec_net_MW cannot be done in log domain because it can be negative
        # 2. no transformations are identified for ind/agr/tra yet.
    }
    """Data pre/post processors for various Y values

    Notes
    -----

    1. `elec_net_MW` cannot be done in log domain because it can be negative

    2. No transformations are identified for ind/agr/tra yet.
    """

    INDUSTRY_LOADSHAPE = None
    AGRICULTURE_LOADSHAPE = None
    TRANSPORTATION_LOADSHAPE = None
    """Default sector loadshapes (None is a flat load)"""

    TRAINING_YEAR = 2018
    """Year of training data"""

    COLUMNS = {
        "temperature_degF": "Outdoor air temperature",
        "humidity_pc": "Relative humidity",
        "global_Wpms": "Global horizontal solar irradiance",
        "direct_Wpms": "Direct normal solar irradiance",
        "diffuse_Wpms": "Diffuse solar irradiance",
        "elec_residential_MW": "Total residential building loads",
        "elec_commercial_MW": "Total commercial building loads",
        "elec_industrial_MW": "Total industrial loads",
        "elec_agricultural_MW": "Total agricultural loads",
        "elec_total_MW": "Total loads",
        "elec_dg_MW": "Total distributed generation",
        "elec_net_MW": "Total net loads",
    }

    def __init__(self,
        state:str,
        county:str,
        *,
        Y:str="elec_total_MW",
        X:str=None,
        dg:bool|pd.DataFrame|None=None,
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

          - `Y`: column to predict (default `elec_total_MW`, see
            `Total.EXOGENOUS_VARIABLES` for the supported columns)

          - `X`: list of columns to use as exogenous variables (defaults to
            `Total.EXOGENOUS_VARIABLES[Y]`)

          - `dg`: not used

          - `date_range`: date/time index to predict or sample (required when
            `samples` is not `None`)

          - `samples`: `None` returns the 2018 training data (`date_range` is
            ignored), `0` returns the prediction, `1` returns one AR sample,
            and `>1` returns the `percentile` of that many AR samples

          - `percentile`: percentile to use when `samples` > 1 (`None`
            returns all samples)

          - `holdout`: not used (see `Total.test`)

          - `refresh`: refresh cache data and refit the estimator

        Returns
        -------

        The data frame is indexed by a UTC `timestamp`. See `Total` for the
        columns.
        """

        # identify location of cached results
        if self.CACHEDIR:
            Cache.CACHEDIR = self.CACHEDIR

        # choose sampling method
        if not samples is None and not isinstance(samples,int):
            raise ValueError(f"{samples=} is not valid")
        if samples is None:

            # no sampling gets training data (also ignores date range)
            data = Total._get_training(state,county,X,Y,refresh)

        else:

            # set default exogenous variable(s)
            if X is None:
                X = self.EXOGENOUS_VARIABLES[Y]

            # sampling requires a valid date range
            assert isinstance(date_range,pd.DatetimeIndex), f"{date_range=} must be Pandas DatetimeIndex"
            if samples == 0:

                # zero samples gets prediction without sampling
                data = Total._get_predict(state,county,date_range,X,Y,refresh)

            elif samples == 1:

                # one sample does not use percentile
                data = Total._get_sample(state,county,date_range,X,Y,refresh)

            elif samples > 1:

                if percentile is None:
                    data = Total._get_samples(state,county,date_range,X,Y,samples,refresh)

                else:
                    # multiple samples uses percentile
                    assert 0<=percentile<=100, f"{percentile=} must be between 0 and 100"
                    data = Total._get_percentile(state,county,date_range,X,Y,samples,percentile,refresh)
            else:
                raise ValueError(f"{samples=} must be a non-negative integer, infinity, or None")

        # make index UTC
        if not data.index.tz:
            data.index = data.index.tz_localize("UTC")
        elif not data.index.tz == "UTC":
            data.index = data.index.tz_convert("UTC")

        super().__init__(data.rename_axis("timestamp"))


    @classmethod
    def _preprocess(cls,data:np.ndarray,name:str):
        """Apply preprocessing transformation to data based on name"""
        try:
            return cls.TRANSFORMATIONS[name][0](data)
        except (KeyError, TypeError):
            return data

    @classmethod
    def _postprocess(cls,data:np.ndarray,name:str):
        """Apply postprocessing transformation to X based on Y"""
        try:
            return cls.TRANSFORMATIONS[name][1](data)
        except (KeyError, TypeError):
            return data

    @classmethod
    def _trim_lags(cls,data:pd.DataFrame,columns:list[str]) -> pd.DataFrame:
        """Set the rows in the exogenous lag windows at head and tail of columns to NaN"""
        lags = [lag for config in cls.TSGAM_CONFIG.exog_config
            for lag in getattr(config,"lags",[])]
        headlag = max([0]+[-x for x in lags])
        taillag = max([0]+lags)
        columns = [data.columns.get_loc(x) for x in columns]
        if headlag > 0:
            data.iloc[:headlag,columns] = float('nan')
        if taillag > 0:
            data.iloc[-taillag:,columns] = float('nan')
        return data

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
        cache = Cache(package="loads",version=2,path=[state,county,f"T_{source}_1h_training.csv.gz"])

        # load refresh from cache
        data = None
        if cache.exists() and not refresh:

            try:
                data = pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0])
                _logger.debug(f"{cache=} ok")
            except Exception as err:
                cache.delete()
                _logger.debug(f"{cache=} {err}")

        else:
            _logger.debug(f"{cache=} (re)generation required")

        # no results available from cache
        if data is None:

            # get training weather data
            data = Weather(state,county,cls.TRAINING_YEAR)

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
                    # DG is a negative load regardless of the sign used by the stock data
                    data["elec_dg_MW"] -= loaddata[f"{source}_dg_MW"].abs()

            # make flat loadshape for industry and agriculture
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
            data[f"{source}_total_MW"] = data[[x for x in data.columns if x.endswith("_MW") and "_dg_" not in x]].sum(axis=1)
            data[f"{source}_net_MW"] = data[f"{source}_total_MW"]

            # finalize net load
            if not nonelec:
                data["elec_net_MW"] += data["elec_dg_MW"]

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

        # get runtime cache name
        cache = (state,county,"|".join(X),Y)

        # return estimator if cache active and found in cache
        if not cls.cache is None and cache in cls.cache and not refresh:

            return cls.cache[cache]

        # get training data
        training = cls._get_training(state,county,X,Y,refresh)

        # create estimator
        estimator = TsgamEstimator(config=cls.TSGAM_CONFIG)

        # fit training data
        estimator.fit(training[X],cls._preprocess(training[Y].values,Y))

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
        estimator = cls._get_estimator(state,county,X,Y,refresh)

        # get the exogenous data
        data = cls._get_weather(state,county,date_range)[X]

        # get the prediction
        data.index = pd.DatetimeIndex([str(x) for x in data.index]) # force index to dt index
        data[Y] = cls._postprocess(estimator.predict(data[X]),Y)

        # remove lag windows from head and tail of training data
        return cls._trim_lags(data,[Y])

    @classmethod
    def _get_sample(cls,
        state:str,
        county:str,
        date_range:pd.DatetimeIndex,
        X:str,
        Y:str,
        refresh:bool=False,
        ) -> pd.DataFrame:
        """Get the AR samples for the specified date range"""

        # get estimator
        estimator = cls._get_estimator(state,county,X,Y,refresh)

        # get the exogenous data
        data = cls._get_weather(state,county,date_range)[X]

        # get the samples
        data[Y] = cls._postprocess(estimator.sample(data[X])[0],Y)

        # remove lag windows from head and tail of training data
        return cls._trim_lags(data,[Y])

    @classmethod
    def _get_samples(cls,
        state:str,
        county:str,
        date_range:pd.DatetimeIndex,
        X:str,
        Y:str,
        n_samples:int,
        refresh:bool=False,
        ) -> pd.DataFrame:
        """Get the AR samples for the specified date range"""

        # get estimator
        estimator = cls._get_estimator(state,county,X,Y,refresh)

        # get the exogenous data
        data = cls._get_weather(state,county,date_range)[X]

        # get the samples
        samples = [data]
        for n,sample in enumerate(estimator.sample(data[X],n_samples=n_samples)):
            samples.append(pd.DataFrame(
                data={f"sample_{n}":cls._postprocess(sample,Y)},
                index=data.index),
            )
        data = pd.concat(samples,axis=1).copy() # copy avoids coming fragmentation warning

        # remove lag windows from head and tail of training data
        return cls._trim_lags(data,[x for x in data.columns if x.startswith("sample_")])

    @classmethod
    def _get_percentile(cls,
        state:str,
        county:str,
        date_range:pd.DatetimeIndex,
        X:str,
        Y:str,
        n_samples:int,
        percentile:int,
        refresh:bool=False,
        ) -> pd.DataFrame:
        """Get the AR sample at specified percentile for the specified date range"""

        data = cls._get_samples(state,county,date_range,X,Y,n_samples,refresh)
        columns = [x for x in data.columns if x.startswith("sample_")]
        data[Y] = np.percentile(data[columns],percentile,axis=1)
        data.drop(columns,inplace=True,axis=1)

        return data

    @classmethod
    def test(cls,
        state:str,
        county:str,
        holdout:pd.DatetimeIndex,
        X:str=["temperature_degF"],
        Y:str="elec_total_MW",
        n_samples:int=0,
        refresh:bool=False
        ) -> pd.DataFrame:
        """Perform a hold-out test on the training data

        Arguments
        ---------

          - `state`: state in which county is located

          - `county`: county to draw data from

          - `holdout`: index (or boolean mask) of the 2018 rows to hold out of
            training

          - `X`: X columns in `loads.total.Total` to use as exogenous variables

          - `Y`: Y column in `loads.total.Total` to fit

          - `n_samples`: number of sample columns to generate (`0` for none)

          - `refresh`: refresh cached training data

        Returns
        -------

          - `pd.DataFrame`: the 2018 X and Y data frame augmented with the
            `predict` column and, when `n_samples` is positive, a `sample`
            column (`n_samples=1`) or `sample_0`, `sample_1`, etc. columns
        """

        # get original data
        data = cls._get_training(state,county,X,Y,refresh=refresh)[X+[Y]].copy()
        daterange = data.index

        # remove holdout data from training
        training = data.copy()
        training.loc[holdout,Y] = float('nan')

        # TODO: drop NaNs until TSGAM accepts NaN inputs
        training.dropna(inplace=True)

        # get estimator
        estimator = TsgamEstimator(config=cls.TSGAM_CONFIG)
        estimator.fit(training[X],cls._preprocess(training[Y].values,Y))

        # get the test data
        data["predict"] = cls._postprocess(estimator.predict(data[X]),Y)
        cls._trim_lags(data,["predict"])
        if n_samples > 0:
            samples = cls._postprocess(estimator.sample(data[X],n_samples=n_samples),Y)
            if samples.shape[0] == 1:
                data["sample"] = samples[0,:]
            else:
                data = pd.concat([data,
                                    pd.DataFrame(
                                        data={
                                            f"sample_{n}":samples[n,:]
                                            for n in range(samples.shape[0])
                                            },
                                        index=data.index)],
                    axis=1)
            cls._trim_lags(data,[x for x in data.columns if x.startswith("sample")])

        return data

    @classmethod
    def _clear_cache(cls):
        """Clear the estimator cache"""
        if not cls.cache is None:
            cls.cache = {}


    @classmethod
    def makeargs(cls,**kwargs):
        """@private Return dict of accepted kwargs by this class constructor"""
        return {x:y for x,y in kwargs.items()
            if x in cls.__init__.__annotations__}

if __name__ == "__main__":
    """Main script

    The main script refreshes the cache with debugging enabled.
    """

    import os, sys
    import matplotlib.pyplot as plt

    pd.options.display.max_columns = None
    pd.options.display.width = None
    pd.options.display.max_rows = None

    refresh = "--refresh" in sys.argv
    debug = "--debug" in sys.argv
    plot = "--plot" in sys.argv
    show = "--show" in sys.argv
    wait = "--wait" in sys.argv

    test_variables = ["elec_total_MW"]

    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)

    test_range = pd.date_range(
        start="2018-01-01 00:00:00+0000",
        end="2018-12-31 23:59:59+0000",
        freq="1h",
        )
    holdout = test_range[test_range.month != (test_range + dt.timedelta(days=7)).month]

    full_range = pd.date_range(
        start="2019-01-01 00:00:00+0000",
        end="2022-12-31 23:59:59+0000",
        freq="1h",
        )

    for state,county in Counties(use_index="SYSTEM",selection="WECC")[["ST","COUNTY"]].values:

        for variable in test_variables:

            try:

                file = f"tests/{state}/{county}/{variable}.csv"
                if os.path.exists(file) and not refresh:
                    try:
                        result = pd.read_csv(file,index_col="timestamp",parse_dates=["timestamp"])
                    except:
                        result = None
                else:
                    result = None

                if result is None:

                    Total._clear_cache()

                    result = Total.test(state,county,holdout,Y=variable).rename({variable:"actual",},axis=1)
                    result["holdout"] = result.index.isin(holdout)
                    tested = result.loc[result["holdout"]]
                    residual = tested["predict"] - tested["actual"]
                    RMSE = np.sqrt(np.nanmean(residual**2))
                    MEAN = tested["actual"].mean()
                    PRMSE = RMSE/MEAN*100 if MEAN != 0 else (0.0 if RMSE == 0 else np.inf)
                    _logger.info(f"{state} {county} {variable} holdout {PRMSE=:.1f}%")

                    Total._clear_cache()

                    columns = Total.EXOGENOUS_VARIABLES[variable]+[variable]
                    tsgam = Total(state,county,Y=variable,date_range=full_range,samples=0)[columns]\
                        .rename({variable:"predict"},axis=1)
                    tsgam["sample"] = Total(state,county,Y=variable,date_range=full_range,samples=1000,percentile=95)[[variable]]
                    result = pd.concat([result,tsgam])

                    result.index.name = "timestamp"

                    os.makedirs(os.path.split(file)[0],exist_ok=True)
                    result.round(3).to_csv(file,index=True,header=True)

                else:

                    _logger.info(f"{file} ok")

                if plot and variable == "elec_total_MW":
                    result.plot(

                        figsize=(20,20),
                        x="temperature_degF",
                        y=["actual","predict","sample"],
                        marker=".",
                        linestyle="",

                        # figsize=(30,15),
                        # y=["training","predict","sample","actual"],
                        # xlabel="Date/Time",

                        ylabel="Power (MW)",
                        title=f"{county} {state} {variable}",
                        grid=True,
                        legend=True,
                        )
                    if show:
                        plt.show(block=wait)
                        if not wait:
                            plt.pause(0.1)
                    elif not os.path.exists(file.replace(".csv",".png")):
                        plt.savefig(file.replace(".csv",".png"))
                    plt.close()

            except Exception as err:

                (_logger.exception if debug else _logger.error)(f"{state} {county} {err}")
