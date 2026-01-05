r"""Load casting module

The load casting module is used to backcast and forecast loads based on
weather. Loads are cast from the source year to any year by adjusting the
load data according to the weekday. The source year is based on the year for
which to source data was developed. For residential and commercial loads,
this is 2018. For industrial and agricultural loads this is 2019.

Note that the weather data provided by NREL for commercial and residential
loads is considered the actual load for the given county. Therefore casting
from 2018 to 2018 does not change the weather, but
`loads.cast.Cast.apply_weather` does apply the specified load model to actual
weather provided with the original load data.

# Methodology

The date/time alignment moves the day of year such that weekends align with
the original day of week from the source year.  For example 2019 days are
shifted by 1 day to align with the weekdays of 2018. If the target year is a
leap year, then the first day is appended to the last day to provide 8784
hours instead of 8760 hours.

The heating and cooling loads are adjusted by computing the heating and
cooling weather sensitivity curves that fit the function $P(x) = \frac L{1+e^
{-k(x-x_0)}}+b$ where $L$, $k$, $x_0$, and $b$ are the parameters of the
sensitivity curve. The load difference between the reference $B(T)$ and
target $B(T')$ weather is applied to the reference load.

The distributed generation is TODO.

# Caveat

- The methodology described above usually results in an increase in total
  heating and cooling energy use. This occurs when projected negative heating
  and cooling loads are clipped to zero. These arise when the temperature
  sensitivity is sufficiently large that the load drops by more than the load
  itself.
"""

import datetime as dt
import calendar
from collections import namedtuple
from typing import TypeVar

import pandas as pd
import numpy as np
import scipy as sp

import matplotlib.pyplot as plt

WEATHER_FIELDS = namedtuple("weather",
    ["temperature","horizontal","normal","diffuse"])(
        "temperature_degF","global_Wpms","direct_Wpms","diffuse_Wpms",
        )
"""Weather data fields"""

ELEC_FIELDS = namedtuple("elec",
    ["baseload","cooling","heating","total","dg","net"])(
        "elec_baseload_MW","elec_cooling_MW","elec_heating_MW",
        "elec_total_MW","elec_dg_MW","elec_net_MW",
        )
"""Electric load data fields"""

NONELEC_FIELDS = namedtuple("nonelec",
    ["baseload","cooling","heating","total"])(
        "nonelec_baseload_MW","nonelec_cooling_MW","nonelec_heating_MW",
        "nonelec_total_MW",
        )
"""Electric load data fields"""

class Cast(pd.DataFrame):
    """Load casting class implementation"""

    DYNAMIC_MODEL_ORDER = 2
    """Dynamic model order (used by `loads.cast.Cast.dynamic_model`)"""

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

        - `data`: load and weather data frame containing load data to cast

        - `year`: year to which load is cast

        - `weather`: target year weather
        """

        # pylint: disable=too-many-locals,invalid-name
        assert isinstance(data,pd.DataFrame), "data is not a Pandas data frame"
        assert isinstance(data.index,pd.DatetimeIndex), "data frame must have datetime index"
        assert isinstance(year,int), "year must be an integer"

        #
        # Adjust for weekday and year change
        #
        # print("\nPROJECTION TO",year,"...\n")

        # protect original data
        data = data.copy()

        # calculate day shift
        shift = dt.date(year,1,1).weekday() - data.index[0].weekday()

        # reindex using day shift
        data.index = pd.DatetimeIndex([str(x).replace("2018",f"{year}")
            for x in data.index]) - dt.timedelta(days=shift)

        # rotate day from beginning of year to end of year
        data.index = pd.DatetimeIndex([str(x).replace(f"{year-1}",f"{year}")
            for x in data.index])

        # sort timestamps
        data.sort_index(inplace=True)

        # add leap day if necessary
        if calendar.isleap(year) and len(data) == 8760:
            leap_day = pd.DataFrame(
                    data=data.iloc[:24].values,
                    columns=data.columns,
                    index=pd.date_range(
                        start=f"{year}-12-31 00:00:00+00:00",
                        end=f"{year}-12-31 23:59:59+00:00",
                        freq="1h",
                        ))
            data = pd.concat([
                        data.reset_index(drop=True),
                        leap_day.reset_index(drop=True)
                    ],
                    axis=0)\
                .set_index(pd.date_range(
                        start=f"{year}-01-01 00:00:00+00:00",
                        end=f"{year}-12-31 23:59:59+00:00",
                        freq="1h",
                        ))

        # preserve reference weather
        for column in WEATHER_FIELDS._asdict().values():
            assert column in data.columns, f"weather {column=} is missing in data"
        reference = data[WEATHER_FIELDS._asdict().values()].copy()

        # apply target weather data
        if not weather is None:
            assert (weather.index == data.index).all(), "weather index does not match data index"
            for column in WEATHER_FIELDS._asdict().values():
                assert column in weather.columns, f"weather {column=} is missing in weather"
                data[column] = weather[column]

        #
        # Calculate cooling and heating sensitivity
        #
        X = data[WEATHER_FIELDS.temperature].ffill().fillna(0)
        Xr = reference[WEATHER_FIELDS.temperature].ffill().fillna(0)
        def fit_curve(x, L, x0, k, b):
            return L / (1 + np.exp(-k*(x-x0))) + b

        # Cooling model fit
        Y = data[ELEC_FIELDS.cooling].ffill().fillna(0)
        cooling_fit, _ = sp.optimize.curve_fit(
            f=fit_curve,
            xdata=X ,
            ydata=Y,
            p0=[max(Y)*0.8, 70, 0.2, 0],
            bounds=[
                (0, 40, 0, 0),
                (np.inf, 100, np.inf, max(Y) if max(Y)>0 else np.inf)
                ],
            method="trf",
            )
        def C(x):
            return fit_curve(x,*cooling_fit)
        data[ELEC_FIELDS.cooling] = (data[ELEC_FIELDS.cooling] + C(X) - C(Xr)).clip(lower=0)

        # Heating model fit
        Y = data[ELEC_FIELDS.heating].ffill().fillna(0)
        heating_fit, _ = sp.optimize.curve_fit(
            f=fit_curve,
            xdata=X ,
            ydata=Y,
            p0=[max(Y)*0.8, 70, -0.2, max(Y)],
            bounds=[
                (0, -40, -np.inf, 0),
                (np.inf, 80, 0, max(Y) if max(Y)>0 else np.inf)
                ],
            method="trf",
            )
        def H(x):
            return fit_curve(x,*heating_fit)
        data[ELEC_FIELDS.heating] = (data[ELEC_FIELDS.heating] + H(X) - H(Xr)).clip(lower=0)

        data[ELEC_FIELDS.total] = sum(data[getattr(ELEC_FIELDS,x)]
            for x in ["baseload","heating","cooling"])
        data[ELEC_FIELDS.net] = data[ELEC_FIELDS.total] + data[ELEC_FIELDS.dg]

        # plt.clf()
        # plt.plot(Xr,Dc(Xr),'.b',label="Cooling sensitivity")
        # plt.plot(Xr,Dh(Xr),'.r',label="Heating sensitivity")
        # plt.xlabel("Temperature (degF)")
        # plt.ylabel("Sensitivity (MW/degF)")
        # plt.grid()
        # plt.show()

        super().__init__(data.sort_index())

if __name__ == '__main__':

    TARGET_YEAR = 2019
    SHOW_PLOTS = False
    try:
        from residential import Residential
        from weather import Weather
    except ImportError:
        from .residential import Residential
        from .weather import Weather
    from fips.counties import Counties

    pd.options.display.max_columns = None
    pd.options.display.width = None

    if SHOW_PLOTS:
        plt.rcParams["figure.figsize"] = (40,20)
        plt.figure()

    for STATE,COUNTY in Counties(use_index=["RO","ST","COUNTY"]).loc["WECC"].index:
        # print("Testing",COUNTY,STATE,"...",flush=True)

        test = Residential(state=STATE,county=COUNTY)
        reference_weather = Weather(STATE,COUNTY)
        test[reference_weather.columns] = reference_weather

        target_weather = reference_weather.copy()
        if calendar.isleap(TARGET_YEAR):
            target_weather = pd.concat([target_weather,target_weather.iloc[:24]])
        target_weather.index = pd.date_range(
            start=f"{TARGET_YEAR}-01-01 00:00:00+00:00",
            end=f"{TARGET_YEAR}-12-31 23:59:59+00:00",
            freq="1h",
            )

        test_ref = Cast(test,2018,reference_weather)
        test_data = Cast(test,TARGET_YEAR,target_weather)

        diff_pc = (1-test_ref["elec_total_MW"].sum()/test_data["elec_total_MW"].sum())
        print(f"{STATE} {COUNTY} {TARGET_YEAR}: {diff_pc*100:+.1f}%",flush=True)

        if SHOW_PLOTS:
            plt.clf()

            plt.suptitle(f"{COUNTY} {STATE} {TARGET_YEAR}")
            plt.subplot(2,2,1)
            plt.plot(test_data.index[:len(test_ref)],
                test_ref.reset_index()["elec_total_MW"],
                label="Reference year")
            plt.plot(test_data["elec_total_MW"],label="Target year")
            plt.xlabel("Hour of year")
            plt.ylabel("Load (MW)")
            plt.title("Load projection")
            plt.grid()
            plt.legend()

            plt.subplot(2,2,3)
            plt.plot(test_data.index[:len(test_ref)],
                test_ref.reset_index()["temperature_degF"],
                label="Reference year")
            plt.plot(test_data["temperature_degF"],label="Target year")
            plt.xlabel("Hour of year")
            plt.ylabel("Temperature ($^\\circ$F)")
            plt.title("Temperature projection")
            plt.grid()
            plt.legend()

            plt.subplot(1,2,2)
            plt.plot(test_ref["temperature_degF"],
                test_ref["elec_total_MW"],
                '.b',
                label="Reference year")
            plt.plot(test_data["temperature_degF"],
                test_data["elec_total_MW"],
                '.r',
                label="Target year")
            plt.xlabel("Temperature ($^\\circ$F)")
            plt.ylabel("Load (MW)")
            plt.title("Temperature vs Load")
            plt.grid()
            plt.legend()

            plt.show()
