"""Build the WECC county balancing authority participation factors

Writes `county_ba.csv`, the fraction of each WECC county's retail load that
is served by each balancing authority (BA), from the EIA Form 861 annual
data for 2018:

  - `Service_Territory_2018.xlsx`: the counties each utility serves in each
    state;

  - `Sales_Ult_Cust_2018.xlsx` (bundled and delivery service only, so
    energy-only retail marketers are not double counted) and
    `Short_Form_2018.xlsx`: each utility's retail sales (MWh) and BA code
    in each state.

Within each state, each utility-BA's sales are spread over the counties it
serves by iterative proportional fitting, so that every utility-BA keeps
its reported sales and every county receives its 2018 retail energy from
`county_mwh.csv` (all counties of the state, including non-WECC ones). A
county's factor for a BA is the share of its fitted energy supplied by
utilities in that BA.

Output columns:

  - `county_st`: `"County ST"` (the 407 WECC counties of `wecc_estimate.csv.gz`)

  - `ba`: EIA BA code as reported in EIA-861 (EIA-930 respondent codes for
    the WECC BAs; non-WECC BAs such as `SWPP` or `ERCO` can appear for
    border counties)

  - `factor`: fraction of the county's load served by the BA; the factors
    of a county sum to one

  - `method`: `eia861` when fitted, `override` when taken from
    `county_ba_overrides.csv`, `state` when no utility reporting sales
    lists the county and the state's BA shares are used instead

The fit cannot tell how much of a county each utility serves, so a county
shared by a large utility and a local one can come out wrong (e.g., SMUD's
Sacramento load spills into Placer). Such counties are corrected in
`county_ba_overrides.csv`, which gives each override's basis. The federal
power marketing administrations (BPA, WAPA) are left out of the fit (see
`EXCLUDE`).

Usage:

    python3 county_ba.py [--source DIR] [--output county_ba.csv]

where `DIR` holds the EIA-861 2018 workbooks. By default the 2018 EIA-861
zip file is downloaded from EIA. The checked-in `county_ba.csv` was built
from the EIA-861 2018 workbooks mirrored in
https://github.com/IMMM-SFA/electricity_entity_boundaries
(`EIA_861_Dataset/2018`).
"""

import io
import os
import sys
import unicodedata
import zipfile

import numpy as np
import pandas as pd
import requests

YEAR = 2018
"""EIA-861 data year"""

URL = f"https://www.eia.gov/electricity/data/eia861/zip/f861{YEAR}.zip"
"""EIA-861 annual data archive"""

ITERATIONS = 1000
"""Maximum number of iterative proportional fitting sweeps"""

TOLERANCE = 1e-9
"""Largest relative county energy error accepted by the fit"""

HERE = os.path.dirname(__file__)


def _key(county:str,state:str) -> str:
    """@private Normalized county key for name matching"""
    name = unicodedata.normalize("NFKD",str(county)).encode("ascii","ignore").decode()
    name = name.lower().replace(".","").replace("'","").strip()
    return f"{name} {state}"


ALIASES = {"shannon SD":"oglala lakota SD"}
"""@private EIA-861 county names that changed"""

EXCLUDE = {1738:"Bonneville Power Administration",27000:"Western Area Power Administration"}
"""Federal power marketing administrations left out of the fit

Their retail deliveries go to a few large customers but their service
territories list dozens of counties, which would spread a few percent of
BPAT or WALC/WACM/SWPP load over counties those BAs do not serve.
"""


def read_eia861(source:str|None=None) -> tuple[pd.DataFrame,pd.DataFrame]:
    """Read the service territory and the utility sales by BA

    Arguments
    ---------

      - `source`: folder holding the EIA-861 workbooks, or `None` to
        download the archive from EIA

    Returns
    -------

      - `territory`: columns `utility`, `state`, `key` (normalized county)

      - `sales`: columns `utility`, `state`, `ba`, `mwh`
    """
    names = {
        "territory": f"Service_Territory_{YEAR}.xlsx",
        "sales": f"Sales_Ult_Cust_{YEAR}.xlsx",
        "short": f"Short_Form_{YEAR}.xlsx",
        }
    if source is None:
        archive = zipfile.ZipFile(io.BytesIO(requests.get(URL,timeout=300).content))
        def read(name,**kwargs):
            return pd.read_excel(archive.open(name),**kwargs)
    else:
        def read(name,**kwargs):
            return pd.read_excel(os.path.join(source,name),**kwargs)

    territory = read(names["territory"])
    territory = territory[pd.to_numeric(territory["Utility Number"],errors="coerce").notna()]
    territory = pd.DataFrame({
        "utility": territory["Utility Number"].astype(int),
        "state": territory["State"],
        "key": [ALIASES.get(x,x) for x in
            (_key(c,s) for c,s in zip(territory["County"],territory["State"]))],
        }).drop_duplicates()

    long = read(names["sales"],header=2)
    long = long[pd.to_numeric(long["Utility Number"],errors="coerce").notna()]
    long = long[long["Service Type"].isin(["Bundled","Delivery"])]
    long = pd.DataFrame({
        "utility": long["Utility Number"].astype(int),
        "state": long["State"],
        "ba": long["BA Code"],
        "mwh": pd.to_numeric(long["Megawatthours.4"],errors="coerce"),
        })
    short = read(names["short"])
    short = short[pd.to_numeric(short["Utility Number"],errors="coerce").notna()]
    short = pd.DataFrame({
        "utility": short["Utility Number"].astype(int),
        "state": short["State"],
        "ba": short["BA Code"],
        "mwh": pd.to_numeric(short["Total Sales (MWh)"],errors="coerce"),
        })
    sales = pd.concat([long,short]).dropna()
    sales = sales[(sales.mwh > 0) & ~sales.utility.isin(EXCLUDE)]
    sales = sales.groupby(["utility","state","ba"],as_index=False).mwh.sum()
    return territory,sales


def fit_state(support:pd.DataFrame,rows:pd.Series,columns:pd.Series) -> pd.DataFrame:
    """Iterative proportional fit of a utility-BA by county energy matrix

    Arguments
    ---------

      - `support`: boolean frame, rows are `(utility,ba)`, columns county
        keys; `True` where the utility serves the county

      - `rows`: utility-BA sales (MWh)

      - `columns`: county retail energy (MWh)

    Returns
    -------

    The fitted energy (MWh) with the same shape as `support`. The row sums
    match `rows` and the column sums match `columns` as closely as the
    support allows.
    """
    A = support.values.astype(float) * columns.values[None,:]
    r = rows.values
    c = columns.values
    for _ in range(ITERATIONS):
        A *= np.where(A.sum(axis=1) > 0,r / np.where(A.sum(axis=1) > 0,A.sum(axis=1),1),0)[:,None]
        total = A.sum(axis=0)
        A *= np.where(total > 0,c / np.where(total > 0,total,1),0)[None,:]
        error = np.abs(A.sum(axis=1) - r) / np.maximum(r,1)
        if error.max() < TOLERANCE:
            break
    return pd.DataFrame(A,index=support.index,columns=support.columns)


def county_ba(source:str|None=None) -> pd.DataFrame:
    """Compute the county BA participation factors

    Arguments
    ---------

      - `source`: folder holding the EIA-861 workbooks, or `None` to
        download them

    Returns
    -------

    Long frame with columns `county_st`, `ba`, `factor` and `method`.
    """
    territory,sales = read_eia861(source)
    energy = pd.read_csv(os.path.join(HERE,"county_mwh.csv"),index_col=0)
    energy = energy.loc[[x for x in energy.index if str(x).endswith(f" {YEAR}")]].sum()
    wecc = pd.read_csv(os.path.join(HERE,"wecc_estimate.csv.gz"),index_col=0,nrows=1).columns
    names = {_key(*x.rsplit(" ",1)):x for x in energy.index}

    records = []
    for state in sorted({x.rsplit(" ",1)[1] for x in wecc}):
        counties = [k for k,x in names.items() if x.endswith(f" {state}")]
        columns = pd.Series([energy[names[k]] for k in counties],index=counties)
        rows = sales[sales.state == state].set_index(["utility","ba"]).mwh
        served = territory[(territory.state == state) & territory.key.isin(counties)]
        served = served[served.utility.isin(rows.index.get_level_values(0))]
        support = pd.DataFrame(False,index=rows.index,columns=counties)
        for utility,key in zip(served.utility,served.key):
            support.loc[utility,key] = True
        rows = rows[support.any(axis=1)]
        support = support.loc[rows.index]
        fitted = fit_state(support,rows,columns)
        by_ba = fitted.groupby(level="ba").sum().T            # counties x BAs
        state_share = by_ba.sum() / by_ba.values.sum()
        for key in counties:
            county_st = names[key]
            if county_st not in wecc:
                continue
            total = by_ba.loc[key].sum()
            if total > 0:
                shares,method = by_ba.loc[key] / total,"eia861"
            else:
                shares,method = state_share,"state"
            for ba,factor in shares[shares > 0].items():
                records.append({"county_st":county_st,"ba":ba,"factor":factor,"method":method})

    result = pd.DataFrame(records)
    overrides = pd.read_csv(os.path.join(HERE,"county_ba_overrides.csv"))
    unknown = set(overrides.county_st) - set(wecc)
    if unknown:
        raise ValueError(f"county_ba_overrides.csv names unknown counties {sorted(unknown)}")
    result = pd.concat([
        result[~result.county_st.isin(overrides.county_st)],
        overrides[["county_st","ba","factor"]].assign(method="override"),
        ])
    result["factor"] = result.factor.round(6)
    result = result[result.factor > 0]
    result["factor"] = result.factor / result.groupby("county_st").factor.transform("sum")
    return result.sort_values(["county_st","factor"],ascending=[True,False]).reset_index(drop=True)


def main(argv:list[str]) -> int:
    """Command line interface"""
    source = None
    output = os.path.join(HERE,"county_ba.csv")
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--source":
            source = args.pop(0)
        elif arg == "--output":
            output = args.pop(0)
        else:
            print(__doc__)
            return 1 if arg not in ("-h","--help") else 0
    county_ba(source).to_csv(output,index=False,float_format="%.6f")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
