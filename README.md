[![Validation](https://github.com/eudoxys/loads/actions/workflows/validate.yaml/badge.svg)](https://github.com/eudoxys/loads/actions/workflows/validate.yaml)
[![Documentation](https://github.com/eudoxys/loads/actions/workflows/deploy-pages.yaml/badge.svg)](https://github.com/eudoxys/loads/actions/workflows/deploy-pages.yaml)

Electric loads data accessor and multi-sector load data tool

`loads` builds hourly, county-level US electric (and non-electric) load models
from public data sources, mostly for the WECC region. It compiles residential,
commercial, industrial, and agricultural loads for 2018, predicts them for
other years from weather with a time-series model (TSGAM), calibrates
county loads to state energy and regional peak targets, and aggregates
counties onto network nodes such as the WECC 240-bus model.

# Documentation

See https://www.eudoxys.com/loads

# Installation

Install using Eudoxys Package Manager:

    pip install --upgrade git+https://github.com/eudoxys/epm
    epm install loads

Install using `pip`.

    pip install git+https://github.com/eudoxys/loads

# Maintenance

## Update docs

To update the documentation run the command

    make docs

## Run tests

To run the tests run the commands

    pip install -e . pytest
    pytest loads/_test

Most tests download data and require NSRDB credentials in
`~/.nsrdb/credentials.json` (see https://www.eudoxys.com/weather). See
[`loads/_test/README.md`](loads/_test/README.md) for details.

## Cache Build

To rebuild the cache for all WECC counties run the main script of the
relevant modules, e.g.,

    python3 -m loads.residential --refresh
    python3 -m loads.commercial --refresh

Building the cache for all WECC counties downloads a large amount of data and
can take many hours.

To save the cache run the command

    cache backup -f filename.tar.gz

To restore the cache run the command

    cache restore -f filename.tar.gz

# Examples

## Command line

Get the Alameda county California residential load data in CSV format

    loads print -S=CA -C=Alameda -D=residential -f=csv

Outputs

    timestamp,elec_baseload_MW,elec_cooling_MW,elec_dg_MW,elec_heating_MW,elec_net_MW,elec_total_MW,nonelec_baseload_MW,nonelec_cooling_MW,nonelec_heating_MW,nonelec_total_MW
    2018-01-01 00:00:00+00:00,45.085,1.109,-1.053,1.772,46.913,47.966,12.102,0.0,34.367,46.469
    2018-01-01 01:00:00+00:00,52.15,0.853,0.0,2.032,55.035,55.035,15.438,0.0,40.053,55.491
    2018-01-01 02:00:00+00:00,58.137,0.531,0.0,3.12,61.789,61.789,16.681,0.0,49.935,66.615
    2018-01-01 03:00:00+00:00,55.909,0.458,0.0,4.672,61.039,61.039,11.9,0.0,64.547,76.447
    ...
    2018-12-31 20:00:00+00:00,41.32,0.725,-6.78,4.226,39.49,46.271,11.824,0.0,53.965,65.789
    2018-12-31 21:00:00+00:00,39.15,0.843,-6.397,3.124,36.719,43.116,9.804,0.0,44.813,54.617
    2018-12-31 22:00:00+00:00,37.711,1.033,-5.342,2.649,36.051,41.393,7.904,0.0,38.068,45.972
    2018-12-31 23:00:00+00:00,38.226,1.382,-3.725,1.664,37.548,41.272,8.399,0.0,30.819,39.218

Without `-D`, the command prints the 2018 county load by sector (see
`loads.total.Total`). Add `-G` to use the county's EIA-861M distributed
generation (see `loads.dgen`) in place of the building stock PV.

## Python code

Get the COMstock data frame for medium office buildings in Alameda County CA.

    from loads import COMstock
    print(COMstock(state="CA",county="Alameda",building_type="CMO"))

Outputs

                               district_cooling  district_heating  district_hotwater  elec_cooling  ...  other_watersystems  other_total     total    floor_area
    2018-01-01 00:00:00+00:00               0.0               0.0                0.0      0.248472  ...            0.001661     0.001661  2.031439  1.035391e+08
    2018-01-01 01:00:00+00:00               0.0               0.0                0.0      0.148115  ...            0.000957     0.000957  1.857834  1.035391e+08
    2018-01-01 02:00:00+00:00               0.0               0.0                0.0      0.112703  ...            0.001011     0.001011  1.742692  1.035391e+08
    2018-01-01 03:00:00+00:00               0.0               0.0                0.0      0.091315  ...            0.000938     0.000938  1.659679  1.035391e+08
    2018-01-01 04:00:00+00:00               0.0               0.0                0.0      0.079424  ...            0.000930     0.000930  1.580334  1.035391e+08
    ...                                     ...               ...                ...           ...  ...                 ...          ...       ...           ...
    2018-12-31 19:00:00+00:00               0.0               0.0                0.0      0.332330  ...            0.003769     0.003769  2.693050  1.035391e+08
    2018-12-31 20:00:00+00:00               0.0               0.0                0.0      0.356295  ...            0.004248     0.004248  2.704405  1.035391e+08
    2018-12-31 21:00:00+00:00               0.0               0.0                0.0      0.390223  ...            0.004254     0.004254  2.719034  1.035391e+08
    2018-12-31 22:00:00+00:00               0.0               0.0                0.0      0.396624  ...            0.004203     0.004203  2.627227  1.035391e+08
    2018-12-31 23:00:00+00:00               0.0               0.0                0.0      0.367452  ...            0.004202     0.004202  2.395476  1.035391e+08

    [8760 rows x 26 columns]

Get the residential building loads data frame for Alameda County CA.

    from loads import Residential
    print(Residential(state="CA",county="Alameda"))

Outputs

                               elec_baseload_MW  elec_cooling_MW  elec_dg_MW  ...  nonelec_cooling_MW  nonelec_heating_MW  nonelec_total_MW
    timestamp                                                                 ...                                                          
    2018-01-01 00:00:00+00:00           45.0850           1.1091     -1.0535  ...                 0.0             34.3669           46.4693
    2018-01-01 01:00:00+00:00           52.1497           0.8527      0.0000  ...                 0.0             40.0531           55.4907
    2018-01-01 02:00:00+00:00           58.1370           0.5313      0.0000  ...                 0.0             49.9345           66.6151
    2018-01-01 03:00:00+00:00           55.9089           0.4585      0.0000  ...                 0.0             64.5472           76.4473
    2018-01-01 04:00:00+00:00           52.8237           0.3425      0.0000  ...                 0.0             78.3935           88.7045
    ...                                     ...              ...         ...  ...                 ...                 ...               ...
    2018-12-31 19:00:00+00:00           41.0822           0.4936     -6.4541  ...                 0.0             67.5158           78.7194
    2018-12-31 20:00:00+00:00           41.3200           0.7251     -6.7804  ...                 0.0             53.9646           65.7889
    2018-12-31 21:00:00+00:00           39.1495           0.8430     -6.3966  ...                 0.0             44.8131           54.6172
    2018-12-31 22:00:00+00:00           37.7114           1.0330     -5.3423  ...                 0.0             38.0684           45.9721
    2018-12-31 23:00:00+00:00           38.2257           1.3822     -3.7245  ...                 0.0             30.8190           39.2178

    [8760 rows x 10 columns]

## Load predictions

Predict the total load of Alameda County CA for 2020 from 2020 weather.

    import pandas as pd
    from loads import Total
    date_range = pd.date_range("2020-01-01 00:00:00+00:00","2020-12-31 23:00:00+00:00",freq="1h")
    print(Total("CA","Alameda",date_range=date_range,samples=0))

Distributed generation (DG) is not included by default. To add the county's
hourly 2020 DG, i.e., EIA-861M small-scale solar allocated to the county by
load share and shaped by weather (see `loads.dgen`), and the resulting net
load use

    print(Total("CA","Alameda",date_range=date_range,samples=0,dg=True))

which adds the `elec_dg_MW` (never positive) and `elec_net_MW` columns. The
same DG is available on its own with `loads.dgen.DG("CA","Alameda",date_range)`,
and `loads.dgen.DG.merge` adds it to any hourly load data frame.

See https://www.eudoxys.com/loads for the `Estimator`, `Calibrate`, `Cluster`,
and `Aggregator` tools.

# Caveat

- Although a data cache is used extensively to avoid multiple/slow queries, the
  processing of this large amount of data can be very time-consuming.

- Some COMstock and RESstock building types have no data in some counties. In
  such cases, zero loads are provided. If logging is set to `DEBUG` a message
  is output.

- Weather data requires NSRDB credentials in `~/.nsrdb/credentials.json`
  (see https://www.eudoxys.com/weather).

# Acknowledgments

- This material is based on work supported by the U.S. Department of Energy’s Office of Electricity through a grant from the Grid Controls and Communications Division
