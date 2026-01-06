"""Load data tests

This script run the load model on each county in WECC. If the load components do not
add up as expected, an error is recorded and the problem records are output to an
error CSV file named `{STATE}_{COUNTY}_errors.csv`.
"""

import sys
import pandas as pd

from residential import Residential
from commercial import Commercial
from industry import Industry
from agriculture import Agriculture

from fips.counties import Counties
counties = Counties(use_index="RO").loc["WECC"].set_index(["ST","COUNTY"]).sort_index()
errors = 0
for state,county in counties.index.values:

    print("Testing",county,state,end="...",flush=True)
    data = Residential(state,county)
    data += Commercial(state,county)
    for sector in [Industry,Agriculture]:
        for field,value in sector(state,county).iterrows():
            data[field] += value[(state,county)]
    data.ffill(inplace=True)
    data.fillna(0.0,inplace=True)

    # check MW totals
    error_index = []
    precision = 3
    for source in ["elec","nonelec"]:

        # check that MW enduses add up to MW totals
        enduse = data[[f"{source}_{x}_MW" for x in ["baseload","cooling","heating"]]]
        total = enduse.sum(axis=1)
        diff = (total - data[f"{source}_total_MW"]).round(precision)
        if ( diff != 0 ).any():
            print(f"ERROR [loads.tests]: {source} MW total load test failed!",file=sys.stderr)
            error_index.extend(diff[diff!=0].index)
            errors += 1

    # check that MW total and DG add up to net
    diff = (data[f"elec_net_MW"] - data[f"elec_total_MW"] - data[f"elec_dg_MW"]).round(precision)
    if ( diff != 0 ).any():
        print("ERROR [loads.tests]: elec MW net load test failed!",file=sys.stderr)
        error_index.extend(diff[diff!=0].index)
        errors += 1

    # save errors, if any
    if error_index:
        data.loc[error_index].to_csv(f"{state}_{county}_errors.csv",index=True,header=True)
    else:
        print("ok")

if errors:
    print(f"{errors} error found!")
else:
    print("No errors found")