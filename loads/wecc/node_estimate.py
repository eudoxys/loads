"""WECC240 node hourly load estimate for 2018 through 2022

Generates `node_estimate.csv.gz`, which contains the uncalibrated estimated
hourly electric load in MW of every WECC240 load node from 2018-01-01 00:00
UTC through 2022-12-31 23:00 UTC, obtained by aggregating the raw
`loads.estimator.Estimator` output of each WECC county onto the nodes, and
adding the loads of the Canadian and Mexican nodes from the `wecc240`
repository. The county-to-node allocation used is saved in
`node_estimate_cf.csv`.

Usage
-----

    python3 node_estimate.py [--wecc240 FOLDER] [--cachedir FOLDER] [--output FILE]

Options
-------
- `-w FOLDER`, `--wecc240 FOLDER`: `wecc240` package folder (default
  `wecc240` in the sibling `wecc240` repository clone, otherwise the copy on
  GitHub)
- `-C FOLDER`, `--cachedir FOLDER`: `cache` folder holding the county
  estimates (default the `cache` package default)
- `-o FILE`, `--output FILE`: output file name (default
  `node_estimate.csv.gz` in this folder)

Description
-----------

```mermaid
flowchart LR
    Cache[Estimate_2018-2022.csv.gz] -->|county MW| mul((x))
    bus_gis.csv -->|in-county load busses| cf
    county_node_map.csv -->|nearest load node| cf
    cf[node_estimate_cf.csv] --> mul
    mul -->|Σ county| add((+))
    Foreign[Canada/*.csv Mexico/*.csv] -->|load_MW| add
    add --> node_estimate.csv.gz
```

1. The uncalibrated hourly load of each county is read from the county
   estimate cache written by `wecc_estimate.py` (`Estimate_2018-2022.csv.gz`).
   These are the raw TSGAM estimates, before the monthly energy calibration
   that is applied to `wecc_estimate.csv.gz`.

2. Each county's load is allocated to nodes using constant contribution
   factors:

   - a county that contains one or more WECC240 load busses (busses with
     positive load, located by their county FIPS code in `bus_gis.csv`) is
     split among the nodes of those busses in proportion to the busses'
     load in the WECC240 case;
   - any other county is allocated entirely to its nearest load node, as
     given by the `load` column of `county_node_map.csv`.

3. The node load is the sum of the allocated county loads. Because each
   county's factors sum to 1, the total WECC US county load is preserved.

4. The loads of the nodes outside the US (see `FOREIGN`) are read from the
   `load_MW` column of the node files in the `wecc240` `Canada` and `Mexico`
   folders, which are named after the nodes, and added to those nodes.

The rows of the output are hourly UTC timestamps. The columns are the node
geohashes, sorted. Values are in MW rounded to 4 decimals.

The contribution factor file `node_estimate_cf.csv` has the columns
`county_st`, `node`, `cf`, and `method` (`bus` or `nearest`).

Caveats
-------

1. The node estimates are not calibrated to EIA energy, node, or
   balancing-authority load data.

2. The split of a county among its load nodes is constant in time and based
   on the WECC240 case bus loads, which are a single snapshot.

3. Busses are assigned to counties by their FIPS code in `bus_gis.csv`, so a
   bus located near a county line serves only that county. Counties without
   a load bus are assigned to their nearest load node even if it is in
   another county.

4. Only nodes that receive load from at least one county or from a foreign
   node file appear in the output.

5. The foreign node files cover local calendar years, so the first hours of
   2018 UTC are missing and are filled with the first available value. The
   Mexicali node (`9mtzm4`) has a constant load because no load shape is
   available.

6. Counties assigned to a foreign node by the nearest-node map (e.g.,
   Boundary ID to `c2u6xt`) add their load to that node's foreign load.

See also
--------
- `wecc_estimate.py`
- `wecc240.data.wecc240_data.read_county_node_map`
"""

OUTPUT = "node_estimate.csv.gz"
"""Default output file name"""

CF_OUTPUT = "node_estimate_cf.csv"
"""County-to-node contribution factor file name"""

PRECISION = 4
"""Number of decimals in output values"""

CF_PRECISION = 6
"""Number of decimals in contribution factors"""

CACHE_NAME = "Estimate_2018-2022.csv.gz"
"""Cache file name for each county's estimate (see `wecc_estimate.CACHE_NAME`)"""

FOREIGN = {
    "c2c10y": "Canada", # British Columbia (BC Hydro)
    "c2u6xt": "Canada", # Alberta (AESO)
    "9mtzm4": "Mexico", # Mexicali (CFE)
    }
"""Nodes outside the US and the `wecc240` folder holding their load file"""

WECC240_URL = "https://raw.githubusercontent.com/eudoxys/wecc240/main/wecc240"
"""Fallback location of the `wecc240` package files"""

# python modules
import os
import sys
import argparse

# third-party modules
import pandas as pd

# eudoxys modules
from cache import Cache

HERE = os.path.dirname(os.path.abspath(__file__))
"""@private Folder containing this script and its input data"""

WECC240_LOCAL = os.path.join(HERE,"..","..","..","wecc240","wecc240")
"""@private Location of the `wecc240` package files in a sibling clone"""

def _wecc240_file(*name:str,folder:str=None) -> str:
    """@private Get the path or URL of a `wecc240` package file"""
    if folder is None:
        folder = WECC240_LOCAL if os.path.exists(WECC240_LOCAL) else WECC240_URL
    return "/".join([folder,*name]) if "://" in folder else os.path.join(folder,*name)

def get_cf(folder:str=None) -> pd.DataFrame:
    """Get the county-to-node contribution factors

    Arguments
    ---------
    - `folder`: `wecc240` package folder or URL (default `WECC240_LOCAL` if
      it exists, otherwise `WECC240_URL`)

    Returns
    -------
    - `pd.DataFrame`: contribution factors
      - `county_st`: county name and state abbreviation
      - `node`: node geohash
      - `cf`: fraction of the county load allocated to the node
      - `method`: `bus` if the county contains load busses, otherwise
        `nearest`
    """
    counties = pd.read_csv(_wecc240_file("data","counties.csv",folder=folder),
        dtype={"FIPS":str}).set_index("FIPS")["COUNTY_ST"]
    node_map = pd.read_csv(_wecc240_file("data","county_node_map.csv",folder=folder),
        index_col="county_st")["load"]
    bus = pd.read_csv(_wecc240_file("data","bus_gis.csv",folder=folder),dtype={"FIPS":str})
    bus = bus[(bus["LOAD"]>0) & bus["FIPS"].isin(counties.index)]

    split = bus.groupby(["FIPS","GEOHASH"])["LOAD"].sum().reset_index()
    split["county_st"] = split["FIPS"].map(counties)
    split["cf"] = split["LOAD"] / split.groupby("FIPS")["LOAD"].transform("sum")
    split["method"] = "bus"
    split = split.rename(columns={"GEOHASH":"node"})

    nearest = node_map[~node_map.index.isin(split["county_st"])]
    nearest = pd.DataFrame({"county_st":nearest.index,"node":nearest.values,
        "cf":1.0,"method":"nearest"})

    result = pd.concat([split[["county_st","node","cf","method"]],nearest])
    result["st"] = [x.split()[-1] for x in result["county_st"]]
    return result.sort_values(["st","county_st","node"]).drop(columns="st")\
        .reset_index(drop=True)

def get_county_estimate(county_st:list[str]) -> pd.DataFrame:
    """Get the uncalibrated county load estimates from the cache

    Arguments
    ---------
    - `county_st`: list of `"County ST"` names

    Returns
    -------
    - `pd.DataFrame`: hourly load in MW with `"County ST"` columns

    Raises
    ------
    - `FileNotFoundError`: a county estimate is not in the cache (run
      `wecc_estimate.py` first)
    """
    data = {}
    missing = []
    for name in county_st:
        state,county = name.split()[-1]," ".join(name.split()[:-1])
        cache = Cache(package="loads",version=0,path=[state,county,CACHE_NAME])
        if not cache.download():
            missing.append(name)
            continue
        data[name] = pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0]).iloc[:,0]
    if missing:
        raise FileNotFoundError(f"no cached estimate for {', '.join(missing)}")
    result = pd.DataFrame(data)
    result.index.name = "timestamp"
    return result

def get_foreign_load(
        index:pd.DatetimeIndex,
        folder:str=None,
        ) -> pd.DataFrame:
    """Get the loads of the nodes outside the US

    Arguments
    ---------
    - `index`: hourly UTC timestamps of the result
    - `folder`: `wecc240` package folder or URL (see `get_cf()`)

    Returns
    -------
    - `pd.DataFrame`: hourly load in MW with node geohash columns

    Hours not covered by a node file are filled with the nearest available
    value.
    """
    data = {}
    for node,country in FOREIGN.items():
        load = pd.read_csv(_wecc240_file(country,f"{node}.csv",folder=folder),
            index_col=[0],parse_dates=[0])["load_MW"]
        load.index = pd.DatetimeIndex(load.index).tz_convert("UTC")
        data[node] = load.reindex(index).bfill().ffill()
    result = pd.DataFrame(data,index=index)
    result.index.name = "timestamp"
    return result

def aggregate(
        county:pd.DataFrame,
        cf:pd.DataFrame,
        ) -> pd.DataFrame:
    """Aggregate county loads onto nodes

    Arguments
    ---------
    - `county`: hourly county loads in MW with `"County ST"` columns
    - `cf`: contribution factors (see `get_cf()`)

    Returns
    -------
    - `pd.DataFrame`: hourly node loads in MW with node geohash columns
    """
    weights = cf.pivot_table(index="county_st",columns="node",values="cf",
        aggfunc="sum",fill_value=0.0).reindex(county.columns)
    node = county.fillna(0.0) @ weights
    return node[sorted(node.columns)]

def main(
        wecc240:str=None,
        cachedir:str=None,
        output:str=None,
        ) -> int:
    """Generate the WECC240 node load estimate

    Arguments
    ---------
    - `wecc240`: `wecc240` package folder (see `get_cf()`)
    - `cachedir`: `cache` folder holding the county estimates
    - `output`: output file name (default `OUTPUT` in this folder)

    Returns
    -------
    - `int`: exit code
    """
    output = output or os.path.join(HERE,OUTPUT)
    if cachedir:
        Cache.CACHEDIR = cachedir

    cf = get_cf(wecc240)
    try:
        county = get_county_estimate(sorted(set(cf["county_st"]),
            key=lambda x:(x.split()[-1],x)))
    except FileNotFoundError as err:
        print(f"ERROR: {err.args[0]}",file=sys.stderr)
        return 1

    node = aggregate(county,cf)
    error = (node.sum(axis=1) - county.fillna(0.0).sum(axis=1)).abs().max()
    if error > 1e-6 * county.sum(axis=1).max():
        print(f"ERROR: aggregation does not preserve total load (max error {error} MW)",
            file=sys.stderr)
        return 1

    foreign = get_foreign_load(node.index,wecc240)
    node = node.add(foreign,fill_value=0.0)
    node = node[sorted(node.columns)]

    cf.round({"cf":CF_PRECISION}).to_csv(os.path.join(os.path.dirname(output),CF_OUTPUT),
        index=False,header=True)
    node = node.round(PRECISION)
    node.to_csv(output,index=True,header=True)
    split = cf[cf["method"]=="bus"]["county_st"].nunique()
    print(f"saved {node.shape[0]} hours x {node.shape[1]} nodes",
        f"({county.shape[1]} counties, {split} allocated by load bus,",
        f"{foreign.shape[1]} foreign nodes) to {output}")

    return 0

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n\n",maxsplit=1)[0])
    parser.add_argument("-w","--wecc240",default=None,help="wecc240 package folder")
    parser.add_argument("-C","--cachedir",default=None,help="cache folder")
    parser.add_argument("-o","--output",default=None,help=f"output file (default {OUTPUT})")
    sys.exit(main(**vars(parser.parse_args())))
