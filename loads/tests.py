"""Load data tests

This script runs the load model on each county in CAISO. If the load
components do not add up as expected, an error is recorded and the problem
records are output to an error CSV file named `{STATE}_
{COUNTY}_errors.csv`. In addition the total load projection for 2020 is
compared to the reported actual load.
"""

import os
import sys
import numpy as np
import pandas as pd

from weather import Weather
from fips import Counties
from loads.total import Total

total = None
year = 2020
refresh = False
precision = 3
# tests = ["CAISO"]

def get_total_load(state,county,refresh=refresh,progress=lambda *x:None):
    progress(f"Residential({state=},{county=},{refresh=})")
    data = Residential(state,county,refresh=refresh)
    progress(f"Commercial({state=},{county=},{refresh=})")
    data += Commercial(state,county,refresh=refresh)
    progress(f"Industrial({state=},{county=})")
    loadshape = pd.DataFrame(
        data = np.ones(len(data.index)),
        index = data.index,
        )
    data += Industry(state,county,loadshape)
    progress(f"Agricultural({state=},{county=})")
    data += Agriculture(state,county,loadshape)
    progress(f"Weather({state=},{county=})")
    weather = Weather(state,county)
    data = Cast(
        data=pd.merge(data.reset_index(),weather.reset_index()).set_index("timestamp"),
        year=year)
    data.index.name = "timestamp"
    return data

if __name__ == "__main__":

    pd.options.display.width = None
    pd.options.display.max_columns = None

    if len(sys.argv) > 1:
        tests = sys.argv[1:]
    else:
        tests = ["CAISO"]

    if not "GITHUB_ACTIONS" in os.environ and "WECC" in tests:
        # WECC load test
        print("Testing WECC...")
        wecc_counties = Counties(use_index="RO").loc["WECC"].reset_index().set_index(["ST","COUNTY"]).sort_index()
        for state,county in wecc_counties.index.values:
            print("Reading",county,state,end="... ",flush=True)
            Total(state,county,year)
            print("... ok")

    # CAISO load test
    if "CAISO" in tests:

        print("Testing CAISO...")
        caiso_data = pd.read_csv(
            os.path.join(os.path.dirname(__file__),f"caiso/{year}.csv"),
            usecols=["CAISO Total"],
            )/1000
        caiso_data.columns = ["elec_actual_MW"]
        caiso_data.index = pd.date_range(
            start=f"{year}-01-01 00:00:00-08:00",
            end=f"{year}-12-31 23:59:59-08:00",
            freq="1h",
            ).tz_convert("UTC")
        caiso_data.index.name="timestamp"
        caiso_data.ffill()

        # Test CAISO load
        caiso_counties = Counties(use_index="REGION").loc["CAISO"].reset_index().set_index(["ST","COUNTY"]).sort_index()
        for state,county in caiso_counties.index.values:

            print("Reading",county,state,end="...",flush=True)

            data = Total(state,county,year)
            if total is None:
                total = data.copy()
            else:
                total += data

            print("ok")

        net = total["elec_net_MW"]
        net_sum = net.sum()/1e6
        net_max = net.max()/1e3
        net_min = net.min()/1e3

        act = caiso_data["elec_actual_MW"]
        act_sum = act.sum()/1e3
        act_max = act.max()
        act_min = act.min()

        test = pd.merge(total.reset_index(),caiso_data.reset_index()).set_index("timestamp")
        err_sum = test["elec_net_MW"].sum()/1e6 - test["elec_actual_MW"].sum()/1e3
        err_max = test["elec_net_MW"].max()/1e3 - test["elec_actual_MW"].max()
        err_min = test["elec_net_MW"].min()/1e3 - test["elec_actual_MW"].min()

        print(f"\n                       Loads      CAISO {year}     Error")
        print(   "                     ----------   ----------   -----------------")
        print(  f"Total energy (TWh)   {net_sum:8.3f}     {act_sum:8.3f}     {err_sum:8.3f} ({err_sum/act_sum*100:+5.1f}%)")
        print(  f"Max power (GW)       {net_max:8.3f}     {act_max:8.3f}     {err_max:8.3f} ({err_max/act_max*100:+5.1f}%)")
        print(  f"Min power (GW)       {net_min:8.3f}     {act_min:8.3f}     {err_min:8.3f} ({err_min/act_min*100:+5.1f}%)")

