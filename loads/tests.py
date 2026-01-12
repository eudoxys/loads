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
from loads.residential import Residential
from loads.commercial import Commercial
from loads.industry import Industry
from loads.agriculture import Agriculture
from loads.cast import Cast

total = None
year = 2020
refresh = False
precision = 3

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

    if not "GITHUB_ACTIONS" in os.environ:
        # WECC load test
        print("Testing WECC...")
        wecc_counties = Counties(use_index="RO").loc["WECC"].reset_index().set_index(["ST","COUNTY"]).sort_index()
        for state,county in wecc_counties.index.values:
            print("Reading",county,state,end="... ",flush=True)
            get_total_load(state,county,progress=lambda x:print(x[:3].lower(),flush=True,end=" "))
            print("... ok")

    # CAISO load test
    print("Testing CAISO...")
    caiso_data = pd.read_csv(
        os.path.join(os.path.dirname(__file__),f"caiso/{year}.csv"),
        usecols=["CAISO Total"],
        )/1000
    caiso_data.columns = ["elec_actual_MW"]
    caiso_data.index = pd.date_range(
        start="2020-01-01 00:00:00-08:00",
        end="2020-12-31 23:59:59-08:00",
        freq="1h",
        ).tz_convert("UTC")
    caiso_data.index.name="timestamp"
    caiso_data.ffill()

    # print(caiso_data)

    # Test CAISO load
    caiso_counties = Counties(use_index="ST").loc["CA"].reset_index().set_index(["ST","COUNTY"]).sort_index()
    # print(caiso.loc["CA"])
    exclude = [
        "Del Norte","Siskiyou", # PAC
        "Modoc", # BPAT
        "El Dorado","Sacramento", # BANC
        "Mariposa","Merced", # TIDC
        "Los Angeles", # LADWP
        "Imperial", # IID (except eastern Riverside)
        ]
    caiso_counties = caiso_counties.reset_index().set_index("COUNTY").drop(exclude,axis=0).reset_index().set_index(["ST","COUNTY"])
    errors = 0
    for state,county in caiso_counties.index.values:

        print("Reading",county,state,end="...",flush=True)
        data = get_total_load(state,county)
        # data = Residential(state,county,refresh=refresh)
        # data += Commercial(state,county,refresh=refresh)
        # for sector in [Industry,Agriculture]:
        #     for field,value in sector(state,county).iterrows():
        #         data[field] += value[(state,county)]
        # data.ffill(inplace=True)
        # data.fillna(0.0,inplace=True)
        # weather = Weather(state,county)
        # data = Cast(
        #     data=pd.merge(data.reset_index(),weather.reset_index()).set_index("timestamp"),
        #     year=year)
        # data.index.name = "timestamp"

        if total is None:
            total = data.copy()
        else:
            total += data

        # check MW totals
        error_index = []
        for source in ["elec","nonelec"]:

            # check that MW enduses add up to MW totals
            enduse = data[[f"{source}_{x}_MW" for x in ["baseload","cooling","heating"]]]
            subtotal = enduse.sum(axis=1)
            diff = (subtotal - data[f"{source}_total_MW"]).round(precision)
            if ( diff != 0 ).any():
                data[f"{source}_total_err"] = diff
                print(f"ERROR [loads.tests]: {source} MW total load test failed!",file=sys.stderr)
                error_index.extend(diff[diff!=0].index)
                errors += 1

        # check that MW total and DG add up to net
        diff = (data[f"elec_net_MW"] - data[f"elec_total_MW"] - data[f"elec_dg_MW"]).round(precision)
        if ( diff != 0 ).any():
            data["elec_net_err"] = diff
            print("ERROR [loads.tests]: elec MW net load test failed!",file=sys.stderr)
            error_index.extend(diff[diff!=0].index)
            errors += 1

        # save errors, if any
        file = f"{state}_{county}_errors.csv"
        if error_index:
            """Save errors"""
            data.loc[sorted(list(set(error_index)))].to_csv(file,index=True,header=True)
        else:
            try:
                os.remove(file)
            except FileNotFoundError:
                pass
            print("ok")

    if errors:
        print(f"{errors} error found!")
    else:
        print("No errors found")

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
    print(  f"Total energy (TWh)   {net_sum:8.3f}     {act_sum:8.3f}     {err_sum:8.3f} ({err_sum/act_sum*100:+5.1f})")
    print(  f"Max power (GW)       {net_max:8.3f}     {act_max:8.3f}     {err_max:8.3f} ({err_max/act_max*100:+5.1f})")
    print(  f"Min power (GW)       {net_min:8.3f}     {act_min:8.3f}     {err_min:8.3f} ({err_min/act_min*100:+5.1f})")

