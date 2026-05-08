"""Distributed generation

"""

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline

from fips import Counties
from weather import Weather
from eia import Form861m

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

    years = [2018,2022] # year start/stop

    # pd.options.display.max_rows = None
    pd.options.display.max_columns = None
    pd.options.display.width = None

    dgen = pd.read_csv("wecc/dgen.csv.gz",index_col=[0],parse_dates=[0])
    dgen.columns = [x.split("_")[0] for x in dgen.columns]

    dates = pd.date_range(f"{min(years)}-01-01 00:00:00+0000",f"{max(years)}-12-31 23:59:59+0000",freq="1h")

    # # Show individual county DG based on weather
    # import matplotlib.pyplot as plt
    # last = None
    # counties = Counties(use_index=["SYSTEM"],selection=["WECC"],set_index=["ST","COUNTY"])
    # for county,data in counties[["LAT","LON","GEOHASH"]].sort_index().iterrows():
    #     solar = DG(*county,dates)
    #     solar.plot(figsize=(20,10))
    #     plt.grid()
    #     plt.xlabel("Date/Time")
    #     plt.ylabel("DG [MW]")
    #     plt.title(f"{county[1]} {county[0]}")
    #     plt.show()

    from fips import Counties
    from energy import Energy
    import numpy as np

    counties = Counties(use_index=["SYSTEM"],selection=["WECC"]).sort_values(["ST","COUNTY"])
    counties["COUNTY"] = [f"{y} {x}" for x,y in counties[["ST","COUNTY"]].values]
    counties.set_index("GEOHASH",inplace=True)

    county_nodes = pd.read_csv(
        "https://github.com/eudoxys/wecc240/raw/refs/heads/main/wecc240/data/county_nodes.csv",
        index_col=[0],
        names=["NODE"]
        )

    nodes = pd.merge(counties,county_nodes,left_index=True,right_index=True)\
        .reset_index()\
        .set_index(["NODE","ST","COUNTY"])
    mapping = nodes.reset_index()[["COUNTY","NODE"]].set_index("COUNTY")["NODE"].to_dict()

    energy = []
    keep = set(counties["COUNTY"])
    for state in counties.ST.unique():
        data = Energy(state,counties=None,year=years)
        data.drop([x for x in data.columns if x not in keep],inplace=True,axis=1)
        energy.append(data)
    energy = pd.concat(energy,axis=1).stack().to_frame("COUNTY_MWH").round(3)
    energy["NODE"] = [mapping[x] for x in energy.index.get_level_values(1)]
    energy.index.names = ("MONTH","COUNTY")
    energy = energy.reset_index().set_index(["NODE","MONTH","COUNTY"])

    totals = energy.groupby(["NODE","MONTH"]).sum().rename({"COUNTY_MWH":"NODE_MWH"},axis=1)

    energy = pd.merge(energy,totals,left_index=True,right_index=True).sort_index()
    energy["COUNTY_CF"] = energy["COUNTY_MWH"] / energy["NODE_MWH"]

    wecc_nodes = set(energy.index.get_level_values(0).unique())

    # read WECC nodal DG
    wecc240_dg = pd.read_csv(
        "https://github.com/eudoxys/wecc240/raw/refs/heads/main/wecc240/data/dgen.csv.gz",
        index_col=[0],dtype=float,parse_dates=[0]
        ).resample("MS").sum().unstack().to_frame("NODE_DG_MWH")
    dg_nodes = set(wecc240_dg.index.get_level_values(0).unique())

    dropset = wecc_nodes - dg_nodes
    energy.drop([x for x in energy.index if x[0] in dropset],inplace=True)

    energy.reset_index(inplace=True)
    energy.set_index(["COUNTY","NODE","MONTH"],inplace=True)
    energy.sort_index(inplace=True)

    # print(energy,flush=True)
    # print(dgen)

    result = []
    for county,node in energy.reset_index().set_index(["COUNTY","NODE"]).index.unique():
        print(county,'->',node,end="...",flush=True)
        county_cf = energy.loc[(county,node),["COUNTY_CF"]]
        dg = dgen[[node]]
        dg["MONTH"] = pd.to_datetime(dg.index.to_period("M").astype(str),utc=True)
        df = pd.merge(dg,county_cf,how="left",left_on="MONTH",right_index=True).ffill()
        df[county] = df[node] * df["COUNTY_CF"]
        result.append(pd.DataFrame(
            data={county:df[county]},
            ))
        print("ok")

    (pd.concat(result,axis=1)/1000).round(3).to_csv("wecc/county_dg.csv",index=True,header=True)
    
    # summary = energy.groupby(["NODE","COUNTY"]).sum().reset_index()
    # summary["ST"] = [x.split()[-1] for x in summary["COUNTY"]]
    # summary["COUNTY"] = [" ".join(x.split()[:-1]) for x in summary["COUNTY"]]
    # print(summary.set_index(["ST","COUNTY","NODE"]).sort_index())


