"""Distributed generation

"""

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline

from fips import Counties
from weather import Weather
from eia import Form861m

pd.options.display.max_columns = None
pd.options.display.width = None

class SolarModel(pd.DataFrame):

    default_model = {
        "global_Wpms": (0.2,0.0),
        "diffuse_Wpms": 0.0,
        "direct_Wpms" : 0.0,
        "temperature_degF": 0.0,
    }

    def __init__(self,
        weather:pd.DataFrame,
        model = None,
        ):
        """Default solar power model"""
        if model is None:
            model = self.default_model
        print(len(weather.index))
        data = pd.DataFrame(
            data={"solar_Wpms":[0.0]*len(weather.index)},
            index=weather.index,
            )
        data.index.name = "timestamp"
        for column,polynomial in model.items():
            if polynomial != 0.0:
                data["solar_Wpms"] += np.polyval(polynomial,weather[column])
        super().__init__(data)

class DG(pd.DataFrame):

    eia_data = {}

    def __init__(self,state,county,date_range,model=None):

        # get default solar model if needed
        if model is None:
            model = SolarModel

        # get total

        # get monthly solar production from EIA
        for year,month in sorted(set((x.year,x.month) for x in dates)):
            if (year,month) not in self.eia_data:
                self.eia_data[(year,month)] = Form861m(year,month).set_index("state")
        eia = pd.concat(self.eia_data.values()).reset_index().set_index(["state"])
        eia = eia.loc[state].set_index("date").sort_index()[["tot_mwh"]]

        # get hourly weather
        weather = []
        for year in sorted(set(x.year for x in dates)):
            weather.append(Weather(state,county,year))
        weather = pd.concat(weather)
        weather.index = pd.DatetimeIndex(weather.index)

        # get hourly solar production from weather
        solar = model(weather.loc[date_range])

        # compute monthly solar production from weather
        energy = solar.resample("1MS").sum()

        # compute monthly scaling from weather to EIA
        scale = (eia.tot_mwh/energy.solar_Wpms).to_frame(name="solar_puMW")

        # compute hourly spline of monthly scaling
        x = [x.timestamp() for x in scale.index.to_pydatetime()]
        y = scale.solar_puMW.values
        spline = CubicSpline(x,y)
        hourly = solar.solar_Wpms * spline([x.timestamp() for x in date_range.to_pydatetime()])

        super().__init__(hourly)

if __name__ == "__main__":

    import matplotlib.pyplot as plt

    dates = pd.date_range("2018-01-01 00:00:00+0000","2022-12-31 23:59:59+0000",freq="1h")

    print(sorted(set((x.year,x.month) for x in dates)))

    last = None
    counties = Counties(use_index=["SYSTEM"],selection=["WECC"],set_index=["ST","COUNTY"])
    for county,data in counties[["LAT","LON","GEOHASH"]].sort_index().iterrows():
        solar = DG(*county,dates)
        solar.plot(figsize=(20,10))
        plt.grid()
        plt.xlabel("Date/Time")
        plt.ylabel("DG [MWh/day]")
        plt.title(f"{county[1]} {county[0]}")
        plt.show()
