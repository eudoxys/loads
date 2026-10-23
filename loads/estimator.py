"""Load estimator

Estimates loads for target years based on sector-level load data for 2018.

The list of allowed values for `EstimatorConfig.weather` is given by the
keys of `WEATHER_CONFIG`, which are columns of [`weather.Weather`](https://www.eudoxys.com/weather/weather/weather.html#Weather.__init__).

When `EstimatorConfig.log` is `True`, the fit and predict operations use the
logarithm of the specified `EstimatorConfig.enduse` field.

For information on `EstimatorConfig.ar`, `EstimatorConfig.solver`, and
`EstimatorConfig.harmonics` see [TSGAM estimator](https://github.com/nimish/estimator).

When `EstimatorConfig.outlier_threshold` is nonzero, the TSGAM outlier
component (with regularization weight `EstimatorConfig.outlier_regularizer`)
is included in the model. The threshold value itself is not yet applied to
the training data.

When `EstimatorConfig.keep_actuals` is `True`, then the reference data is kept
instead of predicted data for the reference year. This is the default.

If no years are specified, then holdout data is withheld from training and an
additional column `status` is created with the following values to
indicate whether data is used for training or holdout testing.
- `T`: training data
- `H`: holdout data

The columns `actual` and `prediction` then contain the reference and
predictions, respectively. The `EstimatorConfig.holdout` value must identify a
frequency, e.g., `6h` for every 6th hour, `5d` for every 5th day, `4w` for
every 4th week, `3m` for every 3rd month. Any positive value is permitted for
the number, and one of `h`, `d`, `w`, and `m` are allowed for the frequency.
Alternatively `EstimatorConfig.holdout` may be a function that takes the
training data frame and returns the index of the holdout rows.

A frequency holdout divides the training data into `N` groups (folds) of
intervals, where `N` is the number in the holdout frequency, and
`EstimatorConfig.fold` selects which group is withheld. With the zero-based
interval index `ndx`, the group is `(ndx + 1) % N` and the holdout is the
group equal to `fold`, which is equivalent to `(ndx - fold) % N == N - 1`.
- `fold=0` (or `False`): every `N`th interval is held out (the default).
- `fold=k` for `0 < k < N`: the holdout is shifted by `k` intervals.
- `fold=True`: the estimator is fit `N` times, once for each fold. Every
  valid row is then held out exactly once, so `prediction` contains the
  out-of-fold prediction for each row, the additional column `fold` gives
  the fold that held it out, and `attrs["folds"]` contains the per-fold
  holdout error statistics (`MAE`, `RMSE`, and `MAPE` in percent) with their
  average over all folds in the row `mean`.

A nonzero `fold` cannot be used with a callable `EstimatorConfig.holdout`.

Examples
--------

The following estimates the 2025 total load for Alameda county in California

    from loads.estimator import Estimator
    Estimator("Alameda CA",[2025])

which returns the data frame

                               temperature_degF  humidity_pc  elec_total_MW
    timestamp
    2025-01-01 00:00:00+00:00              48.2         79.7            NaN
    2025-01-01 01:00:00+00:00              45.7         80.4            NaN
    2025-01-01 02:00:00+00:00              43.9         85.2            NaN
    2025-01-01 03:00:00+00:00              43.9         87.2     304.871177
    2025-01-01 04:00:00+00:00              44.6         87.1     301.929806
    ...                                     ...          ...            ...
    2025-12-31 19:00:00+00:00              50.9         92.1     291.173366
    2025-12-31 20:00:00+00:00              51.4         93.8     289.704876
    2025-12-31 21:00:00+00:00              51.6         95.6     286.522042
    2025-12-31 22:00:00+00:00              51.1         98.1     283.721379
    2025-12-31 23:00:00+00:00              50.7         98.3     284.602747

The following obtains only the residential and commercial building loads

    from loads.estimator import Estimator, EstimatorConfig
    config = EstimatorConfig(sectors=["residential","commercial"])
    Estimator("Alameda CA",[2025],config=config)

which returns the data frame

                               temperature_degF  humidity_pc  elec_total_MW
    timestamp
    2025-01-01 00:00:00+00:00              48.2         79.7            NaN
    2025-01-01 01:00:00+00:00              45.7         80.4            NaN
    2025-01-01 02:00:00+00:00              43.9         85.2            NaN
    2025-01-01 03:00:00+00:00              43.9         87.2      74.260048
    2025-01-01 04:00:00+00:00              44.6         87.1      71.399854
    ...                                     ...          ...            ...
    2025-12-31 19:00:00+00:00              50.9         92.1      60.380677
    2025-12-31 20:00:00+00:00              51.4         93.8      58.817573
    2025-12-31 21:00:00+00:00              51.6         95.6      55.486745
    2025-12-31 22:00:00+00:00              51.1         98.1      52.810050
    2025-12-31 23:00:00+00:00              50.7         98.3      53.879351

The following generates the default 5-day holdout test

    from loads.estimator import Estimator
    df = Estimator("Alameda CA")
    df[df.status=="H"]

which outputs the data frame

                               temperature_degF  humidity_pc      actual  prediction status
    timestamp
    2018-01-04 00:00:00+00:00              50.9         88.1  297.196569  288.690881      H
    2018-01-04 01:00:00+00:00              51.1         84.5  304.703669  295.331078      H
    2018-01-04 02:00:00+00:00              52.0         83.5  309.154469  300.106376      H
    2018-01-04 03:00:00+00:00              50.9         90.0  307.530969  301.964979      H
    2018-01-04 04:00:00+00:00              49.6         95.5  302.760669  298.019750      H
    ...                                     ...          ...         ...         ...    ...
    2018-12-30 19:00:00+00:00              50.0         77.3  291.664369  297.301426      H
    2018-12-30 20:00:00+00:00              53.1         71.3  289.589169  294.544812      H
    2018-12-30 21:00:00+00:00              54.5         68.8  283.976469  291.046255      H
    2018-12-30 22:00:00+00:00              54.5         70.5  282.688469  287.443945      H
    2018-12-30 23:00:00+00:00              51.4         84.2  284.631369  289.012841      H

The first hours of each prediction are NaN because of the exogenous variable
lags in `WEATHER_CONFIG`.

The following runs the 5-day holdout test over all 5 folds and reports the
holdout errors averaged over the folds

    from loads.estimator import Estimator, EstimatorConfig
    df = Estimator("Alameda CA",config=EstimatorConfig(fold=True))
    df.attrs["folds"].loc["mean"]

Caveats
-------

1. Years without weather data cannot be estimated (an `EstimatorError` is
raised).

2. Load growth is not considered. The model is trained on the 2018 sector
loads (residential and commercial loads scaled to the housing units and floor
area used by `loads.residential` and `loads.commercial`, and the NLR
industrial and agricultural estimates), so predictions for other years only
reflect differences in weather and the calendar.

3. `EstimatorConfig.outlier_regularizer` and
`EstimatorConfig.outlier_threshold` are class attributes rather than
`NamedTuple` fields, so they cannot be changed with the `EstimatorConfig`
constructor.

See also
--------
- [TSGAM estimator](https://github.com/nimish/estimator)
- [Eudoxys weather](https://www.eudoxys.com/weather)
- `loads.residential.Residential`
- `loads.commercial.Commercial`
- `loads.industry.Industry`
- `loads.agriculture.Agriculture`
"""

# python imports
import sys
from typing import NamedTuple, Callable
from collections import namedtuple
import requests
import re

# third-party imports
import pandas as pd
import numpy as np
from tsgam_estimator import (
    TsgamEstimator,
    TsgamEstimatorConfig,
    TsgamMultiPeriodicConfig,
    TsgamSplineConfig,
    TsgamArConfig,
    TsgamOutlierConfig,
    TsgamSolverConfig,
    PERIOD_HOURLY_DAILY,
    PERIOD_HOURLY_WEEKLY,
    PERIOD_HOURLY_YEARLY
)
from tsgam_estimator import __version__ as tsgam_version

# eudoxys imports
from weather import Weather
from loads.residential import Residential
from loads.commercial import Commercial
from loads.industry import Industry
from loads.agriculture import Agriculture

VERBOSE = False
"""Enables verbose output from this submodule"""

REFERENCE_YEAR = 2018
"""Reference year for training data"""

WEATHER_CONFIG = {
    'temperature_degF': TsgamSplineConfig(
        n_knots=10,
        lags=[-3, -2, -1, 0],  # Current and 1-3 hours back
        reg_weight=6e-5,
        diff_reg_weight=0.5
    ),
    'humidity_pc': TsgamSplineConfig(
        n_knots=8,
        lags=[-2, -1, 0],  # Current and 1-2 hours back
        reg_weight=6e-5,
        diff_reg_weight=0.5
    ),
    'global_Wpms': TsgamSplineConfig(
        n_knots=8,
        lags=[-1, 0],
        reg_weight=6e-5,
        diff_reg_weight=0.5
    ),
    'direct_Wpms': TsgamSplineConfig(
        n_knots=8,
        lags=[-1, 0],
        reg_weight=6e-5,
        diff_reg_weight=0.5
    ),
    'diffuse_Wpms': TsgamSplineConfig(
        n_knots=8,
        lags=[-1, 0],
        reg_weight=6e-5,
        diff_reg_weight=0.5
    ),
}
"""Default configuration for exogenous weather variables"""

class EstimatorConfig(NamedTuple):
    """Estimator top-level configuration"""

    verbose:bool = False
    """Enable verbose output"""

    debug:bool = False
    """Enable TSGAM debugging"""

    log:bool = True
    """Enable use of log values"""

    ar:bool|int = False
    """Enable autoregression model (`True` uses lags 1 to 4, an integer `n`
    uses lags 1 to `n`)"""

    outlier_regularizer = 1e-4
    """Outlier regularizer"""

    outlier_threshold = 5.0
    """Outlier threshold sigmas (in space of Y or log Y depending on value
    `log`); a nonzero value enables the TSGAM outlier component"""

    solver:str = "CLARABEL"
    """Solver selection"""

    harmonics:list[int]=[4,4,6] # year, week, day
    """Yearly, weekly, and daily harmonics to use"""

    sectors:list[str] = ["residential","commercial","industrial","agricultural"]
    """Load sectors to include"""

    enduse:str = "elec_total_MW" # output variable
    """Enduse aggregate to use"""

    weather:str = ["temperature_degF","humidity_pc"] # input variables
    """Weather variables to use"""

    keep_actuals:bool = True
    """Flag to keep actual data in reference year"""

    holdout:str|Callable = "5d"
    """Holdout frequency for testing, e.g., `'6h'`, `'5d'`, `'4w'`, `'3m'`, or a
    function returning the holdout index of a training data frame"""

    fold:int|bool = 0
    """Holdout fold to withhold (`0` or `False` for every `N`th interval of
    the holdout frequency, `0 < k < N` to shift the holdout by `k` intervals,
    or `True` to run the holdout test on all `N` folds)"""

def _verbose(*args,**kwargs):
    """Verbose output"""
    if VERBOSE:
        if not "file" in kwargs:
            kwargs["file"] = sys.stderr
        if not "flush" in kwargs:
            kwargs["flush"] = True
        print("VERBOSE [loads.estimator]:",*args,**kwargs)

class EstimatorError(Exception):
    """Estimator exception"""

def _parse_holdout(freq:str) -> tuple[int,str]:
    """Parse a holdout frequency

    Arguments
    ---------
    - `freq`: holdout frequency of the form `<N><F>`

    Returns
    -------
    - `tuple[int,str]`: the number of folds `N` and the interval `F`
    """
    try:
        n,m = re.match("([0-9]+)([mwdh])",freq).groups()
    except Exception as err:
        raise EstimatorError(f"{freq=} is not valid") from err
    count = int(n)
    if count <= 0:
        raise EstimatorError(f"{freq=} count must be positive")
    return count,m

def _get_holdout(
        df:pd.DataFrame,
        freq:str,
        fold:int=0,
        ) -> pd.DatetimeIndex:
    """Holdout index function

    Arguments
    ---------
    - `df`: data frame to collect holdout from
    - `freq`: holdout frequency
    - `fold`: holdout fold to withhold, from `0` to `N-1` (default `0`)

    Returns
    -------
    - `pd.DatetimeIndex`: index of holdout date/times

    Holdout frequencies are of the form `<N><F>`. Valid interval frequencies
    `<F>` are over one year, i.e., `h` for hourly, `d` for daily, `w` for
    weekly, and `m` for monthly. The intervals are divided into `N` groups
    with `group = (ndx + 1) % N`, and the resulting holdout extracts the
    intervals in the group equal to `fold`. With `fold=0` this is every
    $N$th interval.
    """
    count,m = _parse_holdout(freq)
    if isinstance(fold,bool) or not isinstance(fold,(int,np.integer)) \
            or not 0 <= fold < count:
        raise EstimatorError(f"{fold=} must be an integer from 0 to {count-1} for {freq=}")

    training = df.dropna()

    match m:
        case "m": # every `count` months of the year
            ndx = training.index.month
        case "w": # week `count` weeks of the year (starting on the first day of year)
            ndx = training.index.day_of_year // 7
        case "d": # every `count` days of the year
            ndx = training.index.day_of_year
        case "h": # every count` hours of the year
            ndx = training.index.day_of_year * 24 + training.index.hour
        case _:
            raise EstimatorError(f"{freq=} '{m}' is invalid")

    holdout = (ndx + 1) % count == fold

    return training.index[holdout]

def _holdout_errors(
        actual:pd.Series,
        prediction:pd.Series,
        ) -> dict[str,float]:
    """Holdout error statistics

    Arguments
    ---------
    - `actual`: actual values
    - `prediction`: predicted values

    Returns
    -------
    - `dict[str,float]`: `MAE`, `RMSE`, and `MAPE` (percent) of the valid
      rows
    """
    error = (prediction - actual).dropna()
    actual = actual[error.index]
    return {
        "MAE": float(error.abs().mean()),
        "RMSE": float(np.sqrt((error**2).mean())),
        "MAPE": float((error/actual).abs().mean()*100),
        }

class Estimator(pd.DataFrame):
    """Load estimator results"""
    def __init__(self,
        county_st:str,
        years:list[int]=None,
        *,
        config:EstimatorConfig=None,
        ):
        """Construct a load estimation for target county and years

        Arguments
        ---------
        - `county_st`: county name and state abbreviation, e.g.,
          `"Alameda CA"`
        - `years`: list of years (default None for holdout test)
        - `config`: estimator configuration (default None for default
          configuration)

        Returns
        -------
        The data frame contains the `EstimatorConfig.weather` columns and the
        `EstimatorConfig.enduse` column for every hour of the requested years
        or, when `years` is `None`, the 2018 weather columns with the
        `actual`, `prediction`, and `status` columns (and the `fold` column
        and `attrs["folds"]` summary when `EstimatorConfig.fold` is `True`).
        """
        assert isinstance(county_st,str), f"{county_st=} must be valid county name"

        county = " ".join(county_st.split()[:-1])
        state = county_st.split()[-1]

        if config is None:
            config = EstimatorConfig()

        # make TSGAM configuration from config
        _config = self._estimator_config(config)

        # forward/backward functions
        def forward(Y):
            return np.log(Y) if config.log else Y
        def backward(Y):
            return np.exp(Y) if config.log else Y

        # collect training data
        X = Weather(state,county,REFERENCE_YEAR)[config.weather]
        Y = forward(self._load_sectors(
            sectors=config.sectors,
            state=state,
            county=county,
            enduse=config.enduse,
            ))

        attrs = {}

        # isolate valid training data
        reference = pd.concat([X,Y],axis=1)
        training = reference.dropna()
        if years is None: # perform holdout test

            fold = config.fold
            if not isinstance(fold,(bool,int,np.integer)):
                raise EstimatorError(f"{fold=} must be an integer or boolean")
            if isinstance(config.holdout,str):
                count,_ = _parse_holdout(config.holdout)
                folds = list(range(count)) if fold is True else [int(fold)]
                holdouts = [_get_holdout(training,config.holdout,k) for k in folds]
            elif callable(config.holdout):
                if fold is True or fold != 0:
                    raise EstimatorError(f"{fold=} is not supported with a callable holdout")
                folds = [0]
                holdouts = [config.holdout(training)]
            else:
                raise EstimatorError(f"holdout={config.holdout!r} is not valid")

            inputs = X[config.weather].copy()
            data = X
            data["actual"] = backward(Y)
            data["prediction"] = float("nan")
            data["status"] = "T"
            if fold is True:
                data["fold"] = pd.Series(pd.NA,index=data.index,dtype="Int64")
                summary = {}

            for k,holdout in zip(folds,holdouts):

                _verbose(f"fitting fold {k} with {len(holdout)} holdout rows")

                # get estimator
                fit = training.drop(holdout)
                estimator = self._get_model(
                    X=fit[config.weather],
                    Y=fit[config.enduse],
                    config=_config)

                # generate predictions
                prediction = pd.Series(backward(estimator(inputs)),index=inputs.index)
                if fold is True: # keep only out-of-fold predictions
                    data.loc[holdout,"prediction"] = prediction[holdout]
                    data.loc[holdout,"fold"] = k
                    summary[k] = _holdout_errors(
                        data.loc[holdout,"actual"],
                        data.loc[holdout,"prediction"])
                else:
                    data["prediction"] = prediction
                data.loc[holdout,"status"] = "H"

            if fold is True:
                summary = pd.DataFrame(summary).T
                summary.index.name = "fold"
                summary.loc["mean"] = summary.mean()
                attrs = {"folds":summary}

        else: # predict for specified

            assert hasattr(years,"__iter__"), f"{years=} must be iterable"
            years = sorted(set(years)) # make sure years are unique and ordered

            estimator = self._get_model(
                X=reference[config.weather],
                Y=reference[config.enduse],
                config=_config)

            # assemble inputs
            X = []
            for year in range(min(years),max(years)+1): # don't leave gaps in X
                try:
                    X.append(Weather(
                            state=state,
                            county=county,
                            year=year,
                            )[config.weather])
                except requests.exceptions.HTTPError:
                    _,error,_ = sys.exc_info()
                    raise EstimatorError(f"weather data is not available for {year=} ({error=})") from None
            X = pd.concat(X)

            # generate outputs
            Y = pd.DataFrame(
                data={config.enduse: backward(estimator(X))},
                index=X.index
                ).sort_index()

            # remove unwanted years
            unwanted = X[~X.index.year.isin(years)].index
            X.drop(unwanted,inplace=True)
            Y.drop(unwanted,inplace=True)

            # replace with actuals
            if REFERENCE_YEAR in years and config.keep_actuals:
                Y.loc[reference.index,config.enduse] = backward(reference[config.enduse])

            # compile final dataframe
            data = pd.concat([X,Y],axis=1)

        # construct dataframe
        super().__init__(data)
        self.attrs.update(attrs)

    @classmethod
    def _estimator_config(cls,
        config:EstimatorConfig,
        ):
        """Create the TSGAM config

        Arguments
        ---------
        - `config`: top-level estimator configuration

        Returns
        -------
        - `TsgamEstimatorConfig`: TSGAM estimator configuration
        """

        # construct harmonics configuration
        multi_periodic_config = TsgamMultiPeriodicConfig(
            num_harmonics=config.harmonics,
            periods=[PERIOD_HOURLY_YEARLY, PERIOD_HOURLY_WEEKLY, PERIOD_HOURLY_DAILY],
            reg_weight=6e-5
        )

        # construct exogenous variables configuration
        exog_config = []
        for var_name in config.weather:
            exog_config.append(WEATHER_CONFIG[var_name])

        # autoregression configuration
        ar_config = TsgamArConfig(
            lags=list(range(1,config.ar+1)) if isinstance(config.ar,int) else [1,2,3,4],
            l1_constraint=0.97
        ) if config.ar else None

        # outlier configuration
        outlier_config = TsgamOutlierConfig(
            reg_weight=config.outlier_regularizer,
            period_hours=24.0  # Daily outliers
        ) if config.outlier_threshold else None

        # solver configuration
        solver_config = TsgamSolverConfig(
            solver=config.solver,
            verbose=config.verbose
        )

        # main TSGAM config
        return TsgamEstimatorConfig(
            multi_periodic_config=multi_periodic_config,
            exog_config=exog_config,
            ar_config=ar_config,
            outlier_config=outlier_config,
            solver_config=solver_config,
            random_state=42,
            debug=config.debug,
        )

    @classmethod
    def _get_model(cls,
        X:pd.DataFrame,
        Y:pd.DataFrame,
        config:TsgamEstimatorConfig,
        ) -> Callable:
        """Run training

        Arguments
        ---------
        - `X`: input values (1 or more columns)
        - `Y`: output values (only 1 column)
        - `config`: TSGAM configuration to use

        Returns
        -------
        - `Callable`: estimator function (takes only an input dataframe)
        """

        # TODO: apply outlier threshold to Y values

        model = TsgamEstimator(config)
        model.fit(X,Y.values.ravel())
        return lambda x:model.predict(x)

    @classmethod
    def _load_sectors(cls,
        sectors:list[str],
        state:str,
        county:str,
        enduse:str,
        ) -> pd.DataFrame:
        """Load sectors

        Arguments
        ---------
        - `sectors`: list of sectors to load
        - `state`: state abbrevation
        - `county`: county name
        - `enduse`: enduse

        Returns
        -------
        - `pd.DataFrame`: data frame of load data
        """
        assert isinstance(sectors,list), f"{sectors=} must be list of sector names"
        assert len(sectors) > 0, f"{sectors=} must contain at least one sector name"
        sector = sectors[0]
        match sector:
            case "residential":
                data = Residential(state,county)[[enduse]]
            case "commercial":
                data = Commercial(state,county)[[enduse]]
            case "industrial":
                data = Industry(state,county).loc[enduse].values[0]
            case "agricultural":
                data = Agriculture(state,county).loc[enduse].values[0]
            case _:
                raise EstimatorError(f"{sector=} is not a valid load sector")

        if len(sectors) > 1:
            data += cls._load_sectors(sectors[1:],state,county,enduse)

        return data

if __name__ == '__main__':

    VERBOSE = True
    pd.options.display.width = None

    print("Example 1")
    print("---------")
    print(Estimator("Alameda CA",[2025]))

    print("Example 2")
    print("---------")
    config = EstimatorConfig(sectors=["residential","commercial"])
    print(Estimator("Alameda CA",[2025],config=config))

    print("Example 3")
    print("---------")
    df = Estimator("Alameda CA")
    print(df[df.status=="H"])

    print("Example 4")
    print("---------")
    df = Estimator("Alameda CA",config=EstimatorConfig(fold=True))
    print(df.attrs["folds"])