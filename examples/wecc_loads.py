"""This script generates the WECC total loads for the years 2018 through 2022

"""

import pandas as pd

from fips import Counties
from loads.total import Total
from eia import HS861m
from cache import Cache

# Step 0: setup and configuration
start = "2018-01-01 00:00:00+0000"
stop = "2022-12-31 23:59:59+0000"
refresh = False # flag is induce full refresh of cache
# pd.options.display.max_rows = None 
pd.options.display.max_columns = None
pd.options.display.width = None

date_range = pd.date_range(start,stop,freq="1h")

# Step 1: get the counties for which data needs to be collected
print("Loading counties",end="...",flush=True)
wecc_counties = Counties(use_index=["RO"],selection="WECC",set_index=["ST","COUNTY"])
# print(wecc_counties)
print("ok")

# Step 2: get DG data
print("Loading county DG",end="...",flush=True)
wecc_dg = pd.read_csv("county_dg.csv.gz",index_col=[0],parse_dates=[0])
# print(wecc_dg["Apache AZ"].to_frame("Apache AZ").max(),flush=True)
print("ok")

# Step 3: get county energy contribution factors to state energy
print("Loading county CF",end="...",flush=True)
wecc_cf = pd.read_csv("county_cf.csv",index_col=[0])
wecc_cf.index = pd.DatetimeIndex(wecc_cf.index,tz="UTC")
wecc_cf.index.name="timestamp"
print("ok")

# Step 4: get state energy consumption
print("Loading state energy demand",end="...",flush=True)
wecc_mwh = []
states = wecc_counties.index.get_level_values(0).unique().tolist()
for dt in pd.date_range(start,stop,freq="MS"):
    mwh = HS861m(dt.year,dt.month)
    # print(mwh)
    wecc_mwh.append(mwh.loc[states,"tot_energy_mwh"].to_frame(dt).T)
wecc_mwh = pd.concat(wecc_mwh)
print("ok")

# Step 5: get total loads with the DG data
totals = []
for state,county in wecc_counties.index:
    county_st = f"{county} {state}"
    print(f"Processing {county} {state}...",flush=True)

    cache = Cache(package="loads",version=0,path=[state,county,f"Total_{start[:4]}-{stop[:4]}.csv"])
    if cache.exists():
        load = pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0])
    else:
        load = Total(state,county,date_range=date_range,refresh=refresh,samples=0).round(3)
        load.to_csv(cache.pathname,index=True)

    # get county DG
    if county_st in wecc_dg.columns:
        dg = wecc_dg[county_st]
        load["elec_dg_MW"] = dg
    else:
        load["elec_dg_MW"] = 0.0
        dg = load["elec_dg_MW"]

    # get state-level energy total
    mwh = wecc_mwh[state].resample("1h").ffill()
    load["state_mwh"] = mwh

    # get county contribution factor to state-level energy total
    cf = wecc_cf[county_st].resample("1h").ffill()
    load["county_cf"] = cf

    # get original county-level energy total
    old_mwh = load["elec_total_MW"].resample("MS").sum().resample("1h").ffill()
    load["old_mwh"] = old_mwh

    # calculate actual county-level energy total
    new_mwh = mwh * cf + dg.resample("MS").sum().resample("1h").ffill()
    load["new_mwh"] = new_mwh
    
    # calculate new MW
    load["new_MW"] = load["elec_total_MW"] * new_mwh / old_mwh

    totals.append(load["new_MW"].to_frame(county_st).round(3))
    print(load.dropna())

    result = pd.concat(totals,axis=1)
    result.index.name = "timestamp"
    result.to_csv("county_totals.csv",index=True)

    print("ok")
