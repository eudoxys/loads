"""Distributed generation

This module processes county DG data.
"""

import os
from warnings import warn

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline
import matplotlib.pyplot as plt

from fips import Counties
from weather import Weather
from eia import Form861m

class SolarModel(pd.DataFrame):
    """Solar DG model"""
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
    """Distribution generation dataframe"""
    eia_data = {}
    dg_data = None

    def __init__(self,
        state:str,
        county:str,
        date_range:pd.DatetimeIndex|None=None,
        source:str="wecc/county_dg.csv.gz",
        on_missing:str="fillna"
        ):

        assert on_missing in ["fillna",None], f"{on_missing=} is invalid"

        if self.dg_data is None:

            # get default solar model if needed
            if source == SolarModel:

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

            elif isinstance(source,str):

                # use specified data source
                hourly = pd.read_csv(source,index_col=["timestamp"],parse_dates=["timestamp"])

                # extract date_range
                if isinstance(date_range,pd.DatetimeIndex):

                    # isolate missing date/times
                    missing = [x for x in date_range if x not in hourly.index]

                    # reduce to date/times founds
                    hourly = hourly.loc[[x for x in date_range if x in hourly.index]]

                    # fill missing, if desired
                    if on_missing == "fillna":
                        hourly = pd.concat([hourly,pd.DataFrame(index=missing)],axis=0).sort_index()
            
            else:
            
                raise ValueError(f"{source} is not valid")

            self.dg_data = hourly

        county_st = f"{county} {state}"
        if county_st in self.dg_data.columns:
            result = self.dg_data[[county_st]].rename({county_st:"elec_dg_MW"},axis=1)
        else:
            result = pd.DataFrame(
                data=(0 for x in date_range),
                index=date_range,
                )
        super().__init__(result)

def compile(
    source:str="wecc/dgen.csv.gz",
    target:str="wecc/county_dg.csv.gz",
    county_file:str="https://github.com/eudoxys/wecc240/raw/refs/heads/main/wecc240/data/county_nodes.csv",
    system:str="WECC",
    ):
    """Compile DG data

    Arguments
    ---------

    - `source`: source node power DG data file

    - `target`: target county power DG data file

    - `county_file`: county energy DG data file

    - `system`: system for which counties will be compiled

    """

    from loads.energy import Energy

    years = [2018,2022] # year start/stop

    # read the raw from NREL
    dgen = pd.read_csv(source,index_col=[0],parse_dates=[0])
    dgen.columns = [x.split("_")[0] for x in dgen.columns]

    # setup the date/time index
    dates = pd.date_range(f"{min(years)}-01-01 00:00:00+0000",f"{max(years)}-12-31 23:59:59+0000",freq="1h")

    # get the counties in the system
    counties = Counties(use_index=["SYSTEM"],selection=[system]).sort_values(["ST","COUNTY"])
    counties["COUNTY"] = [f"{y} {x}" for x,y in counties[["ST","COUNTY"]].values]
    counties.set_index("GEOHASH",inplace=True)

    # read the nodes list
    county_nodes = pd.read_csv(county_file,index_col=[0],names=["NODE"])

    # merge counties and nodes to get the mapping
    nodes = pd.merge(counties,county_nodes,left_index=True,right_index=True)\
        .reset_index()\
        .set_index(["NODE","ST","COUNTY"])
    mapping = nodes.reset_index()[["COUNTY","NODE"]].set_index("COUNTY")["NODE"].to_dict()

    # collate the energy data
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

    # calculate the totals
    totals = energy.groupby(["NODE","MONTH"]).sum().rename({"COUNTY_MWH":"NODE_MWH"},axis=1)

    # merge the totals with the energy data
    energy = pd.merge(energy,totals,left_index=True,right_index=True).sort_index()
    energy["COUNTY_CF"] = energy["COUNTY_MWH"] / energy["NODE_MWH"]

    # get the set of nodes
    system_nodes = set(energy.index.get_level_values(0).unique())

    # read WECC nodal DG
    system_dg = pd.read_csv(source,index_col=[0],dtype=float,parse_dates=[0])\
        .resample("MS").sum().unstack().to_frame("NODE_DG_MWH")
    dg_nodes = set([x.split("_")[0] for x in system_dg.index.get_level_values(0).unique()])
    # print(totals.loc["9qndpr"])
    # print(energy.loc["9qndpr"])
    # print("9qndpr" in system_nodes)
    print("9myzug" in dg_nodes)
    quit()

    # identify nodes to drop because they have no DG data
    dropset = system_nodes - dg_nodes
    if dropset:
        warn(f"the following {len(dropset)} nodes have no DG: {', '.join(dropset)}")
        energy.drop([x for x in energy.index if x[0] in dropset],inplace=True)

    # setup the result index
    energy.reset_index(inplace=True)
    energy.set_index(["COUNTY","NODE","MONTH"],inplace=True)
    energy.sort_index(inplace=True)

    # finalize county-level DG
    result = []
    for county,node in energy.reset_index().set_index(["COUNTY","NODE"]).index.unique():
        print(county,'->',node,end="...",flush=True)
        county_cf = energy.loc[(county,node),["COUNTY_CF"]]
        dg = dgen[[node]]
        dg["MONTH"] = pd.to_datetime(dg.index.to_period("M").astype(str),utc=True)
        print(dg)
        quit()
        df = pd.merge(dg,county_cf,how="left",left_on="MONTH",right_index=True).ffill()
        df[county] = df[node] * df["COUNTY_CF"]
        result.append(pd.DataFrame(
            data={county:df[county]},
            ))
        print("ok")

    result = (pd.concat(result,axis=1)/1000).round(3)

    if target is None:
        return result
    else:
        result.to_csv(target,
            index=True,
            header=True,
            compression="gzip" if target.endswith(".gz") else None,
            )

if __name__ == "__main__":

    refresh = True # force recompile of county-level DG data

    # pd.options.display.max_rows = None
    pd.options.display.max_columns = None
    pd.options.display.width = None

    # output = "wecc/county_dg.csv.gz"
    output = "wecc/county_dg.csv"
    if not os.path.exists(output) or refresh:
        compile(target=output)

    # date_range = pd.date_range(
    #     start=f"2018-01-01 00:00:00+0000",
    #     end=f"2022-12-31 23:59:59+0000",
    #     freq="1h")

    # def dump(x):
    #     print(f"{x}{str(globals()[x])[len(x):]}")

    # dg_MW = DG("AZ","Apache",date_range)
    # dg_MWh = dg_MW.resample("MS").sum()
    # dump("dg_MWh")
    # dg_MWh = dg_MW.resample("YS").sum()
    # dump("dg_MWh")
    
    # peak_MW = dg_MW.max().tolist()[0]
    # peak_dt = dg_MW[dg_MW.elec_dg_MW==peak_MW]
    # dump("peak_dt")


    # pd.read_csv(output,index_col=["timestamp"],parse_dates=["timestamp"]).resample("ME").sum()["San Diego CA"].plot(grid=True)
    # plt.show()
