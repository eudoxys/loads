"""Load casting module

The load casting module is used to backcast and forecast loads. Loads can be
cast from the source year to any year by adjusting the load data according to
the weekday. The source year is based on the year for which to source data
was developed. For residential and commercial loads, this is 2018. For industrial
and agricultural loads this is 2019. 

Note that the weather data provided by NREL for commercial and residential
loads is considered the actual load for the given county. Therefore casting
from 2018 to 2018 does not change the weather, but
`loads.cast.Cast.apply_weather` does apply the specified load model to actual
weather provided with the original load data.
"""

import os
import datetime as dt
import warnings
from typing import TypeVar

import pandas as pd
import numpy as np
import scipy as sp

class Cast(pd.DataFrame):
    """Load casting class implementation"""

    DYNAMIC_MODEL_ORDER = 3
    """Dynamic model transfer function order (used by `loads.cast.Cast.pwld` model)"""

    PERIOD_HARMONICS = {
        365.2425:4, # year
        7*24:4, # week
        24:6, # day
    }
    """SPCQE default period harmonics"""

    def __init__(self,
        data:pd.DataFrame,
        year:int,
        weather:TypeVar('loads.weather.Weather')|None=None
        ):
        """Construct a load caster

        # Argument

        - `data`: load data frame containing load data to cast

        - `year`: year to which load is cast

        - `weather`: reference weather to use with `loads.cast.Cast.apply_weather`
        """
        assert isinstance(data,pd.DataFrame), "data is not a Pandas data frame"
        assert isinstance(data.index,pd.DatetimeIndex), "data frame must have datetime index"
        assert isinstance(year,int), "year must be an integer"

        # merge weather data if any...
        if not weather is None:
            data = pd.concat([data,weather],axis=1)

        # ...or make a copy of data before munging the index
        else:
            data = data.copy()

        # adjust for weekday and year change
        shift = dt.date(year,1,1).weekday() - data.index[0].weekday()
        data.index = pd.DatetimeIndex([str(x).replace("2018",f"{year}")
            for x in data.index]) - dt.timedelta(days=shift)
        data.index = pd.DatetimeIndex([str(x).replace(f"{year-1}",f"{year}")
            for x in data.index])

        super().__init__(data.sort_index())

    def apply_weather(self,
        weather:TypeVar('loads.weather.Weather'),
        model:str,
        **kwargs,
        ) -> pd.DataFrame:
        """Apply weather model

        # Arguments

        - `weather`: weather data to use for model

        - `model`: modeling method to use for weather update to model, i.e.,

          - `"pwls"`: piecewise linear static model with heating and cooling balance
            temperatures as specified by
            `loads.cast.Cast.HEATING_BALANCE_TEMPERATURE` and
            `loads.cast.Cast.COOLING_BALANCE_TEMPERATURE`, respectively.

          - `"pwld"`: piecewise linear dynamic model with heating and cooling balance
            temperatures as specified by
            `loads.cast.HEATING_BALANCE_TEMPERATURE` and
            `loads.cast.COOLING_BALANCE_TEMPERATURE`, respectively.

          - `"smp"`: smooth multi-periodic model from https://github.com/cvxgrp/spcqe.

        - `**kwargs`: model options (see `apply_{model}` for details)

        # Returns

        - `pandas.DataFrame`: load modeled with weather data provided
        """
        if hasattr(self,f"{model}_model"):
            return getattr(self,f"{model}_model")(weather,**kwargs)
        raise ValueError("f{model=} is invalid")

    def static_model(self,
        weather:TypeVar('loads.weather.Weather')|None=None,
        return_model:bool=False
        ) -> pd.DataFrame:
        r"""Apply static  model

        # Arguments

        - `weather`: target weather data (None uses original reference data)

        - `return_model`: enable returning callable model function instead of data frame

        # Returns

        - `pandas.DataFrame`: load cast static (baseline) model

        - `dict[str, callable]: callable load model as a function of weather parameter

          Parameters:

            - `cooling` parameter is `temperature_degF`

            - `heating` parameter is `temperature_degF`

            - `baseload` parameter is `timestamp`

            - `dg` parameters are `global_Wpms`, `direct_Wpms`, and `diffuse_Wpms`

        # Description

        The static model fits a sigmoid baseline temperature-dependent model
        to the heating and cooling loads, a temperature-dependent Fourier
        baseline model to the baseline loads, and a solar-dependent DG model.
        The total and net loads are summed as usual.

        # Methodology

        The cooling and heating static models are constructed in two steps.

        1. Compute the baseline model $B=(L, k, T_0,b)$ such that
        $$
            \frac L {1+\exp(-k(T[k]-T_0))} + b - \bar P[k]
        $$
        is least-squares minimal over the samples $k \in (1,8760)$ 

        2. Fit the discrete-time dynamic model $A=(a_0,a_1,a_2,a_3)$ such that
        $$
            a_0 \bar P[k] + a_1 P[k-1] + a_2 P[k-2] + a_3 T[k] - P[k]
        $$
        is least-squares minimal over the samples $k \in (3,8760)$.

        The baseload model is TODO.

        The DG model is TODO.
        """
        if weather is None:
            weather = self
        assert isinstance(weather,pd.DataFrame), "weather is not a Pandas data frame"
        assert isinstance(weather.index,pd.DatetimeIndex), "weather frame must have datetime index"
        assert (weather.index == self.index).all(), "weather index must match load data index"
        for column in ["temperature_degF","global_Wpms","diffuse_Wpms","direct_Wpms"]:
            assert column in self.columns, f"{column} not found"

        X = self["temperature_degF"]
        Y = self[f"elec_cooling_MW"]
        t = self.index.values

        # cooling model fit
        sigmoid = lambda x, L, x0, k, b: L / (1 + np.exp(-k * (x - x0))) + b
        initial_guess = [max(Y)*0.8, 70, 0.2, 0]
        sfit, err = sp.optimize.curve_fit(
            sigmoid, X ,Y, initial_guess,
            method="trf",
            bounds=[(0, 40, 0, 0), (np.inf, 100, np.inf, max(Y))],
            )

        if not return_model:
            result = self.copy()
            result["elec_cooling_MW"] = sigmoid(X, *sfit)
            return result
        else:
            return {
                "cooling": lambda x:sigmoid(x,*sfit)
                }

    def dynamic_model(self,
        baseline:list[float],
        weather:TypeVar('loads.weather.Weather')|None=None,
        order:int=None,
        ):
        """Apply dynamic model

        # Arguments

        - `weather`: target weather data (None uses original reference data)

        - `order`: dynamic model order (defaults to
          `loads.cast.Cast.DYNAMIC_MODEL_ORDER`)

        # Returns

        - `pandas.DataFrame`: load cast using model
        """
        if weather is None:
            weather = self
        assert isinstance(weather,pd.DataFrame), "weather is not a Pandas data frame"
        assert isinstance(weather.index,pd.DatetimeIndex), "weather frame must have datetime index"
        assert weather.index == self.index, "weather index must match load data index"
        for column in ["temperature_degF","global_Wpms","diffuse_Wpms","direct_Wpms"]:
            assert column in self.columns, f"{column} not found"

        raise NotImplementedError("TODO")
    
    def spcqe_model(self,
        weather:TypeVar('loads.weather.Weather')|None=None,
        periods:np.ndarray|None=None,
        harmonics:np.ndarray|None=None,
        ):
        """Apply smooth multi-period consistent quantile estimator (SPCQE) model

        # Arguments

        - `weather`: target weather data (None uses original reference data)

        - `periods`: periods to use (defaults to
          `loads.cast.Cast.PERIOD_HARMONICS` keys)

        - `harmonics`: number of harmonics to use (defaults to
          `loads.cast.Cast.PERIOD_HARMONICS` values)

        # Returns

        - `pandas.DataFrame`: load cast using model
        """
        assert isinstance(weather,pd.DataFrame), "weather is not a Pandas data frame"
        assert isinstance(weather.index,pd.DatetimeIndex), "weather frame must have datetime index"
        assert weather.index == self.index, "weather index must match load data index"
        assert "temperature_degF" in self.columns
        raise NotImplementedError("TODO")

if __name__ == '__main__':

    try:
        from residential import Residential
        from weather import Weather
    except ImportError:
        from .residential import Residential
        from .weather import Weather

    STATE = "CA"
    COUNTY = "Alameda"

    pd.options.display.max_columns = None
    pd.options.display.width = None

    print("Testing",COUNTY,STATE,"...",flush=True)
    cache = os.path.join(".cache",f"{STATE}_{COUNTY}_R.csv")
    if os.path.exists(cache):
        test = pd.read_csv(cache,index_col=0,parse_dates=[0])
    else:
        test = Residential(state=STATE,county=COUNTY)
        test.to_csv(cache)

    START = "01-01"
    END = '01-08'
    test.loc[pd.date_range(
        f"2018-{START} 00:00:00-0700",
        f"2018-{END} 00:00:00-0700",
        freq="1h")]["elec_baseload_MW"].plot(grid=True).figure.savefig(f".cache/cast_{STATE}_{COUNTY}_2018_w01.png")

    import matplotlib.pyplot as plt
    
    for YEARTO in range(2019,2025):
        plt.clf()
        result = Cast(test,YEARTO,Weather(STATE,COUNTY))

        result.loc[pd.date_range(
            f"{YEARTO}-{START} 00:00:00-0700",
            f"{YEARTO}-{END} 00:00:00-0700",
            freq="1h")]["elec_baseload_MW"].plot(grid=True).figure.savefig(f".cache/cast_{STATE}_{COUNTY}_{YEARTO}_w01.png")

    X = result["temperature_degF"].values
    model = result.static_model()
    for LOAD in ["cooling"]:

        Y = result[f"elec_{LOAD}_MW"]
        Yr = model[f"elec_{LOAD}_MW"]
        
        plt.clf()
        plt.plot(X,Y,".b",label="Actual")
        plt.plot(X,Yr,".r",label="Model")
        plt.xlabel("Temperature ($^\\circ$F)")
        plt.title(f"{COUNTY} {STATE} {LOAD}")
        plt.ylabel("Load (MW)")
        plt.grid()

        plt.show()
