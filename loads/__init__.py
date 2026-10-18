"""Electric load data accessors

Syntax
------

    loads {print,plot,viewer,test,help,info} [-h] [-S STATE] [-C COUNTY]
          [-D {residential,commercial,industrial,agricultural,weather,total}]
          [-Y YEAR] [-o OUTPUT] [-B BUILDING_TYPE]
          [-f {csv,gzip,zip,xlsx,pie,scatter,plot}] [-p PRECISION] [-w] [-d]

Positional arguments
--------------------

  - `print`: output text

  - `plot`: output graphics

  - `viewer`, `test`, `help`, `info`: accepted by the parser but not
    functional in this version (see `loads.cli`)

Optional arguments
------------------

  - `-B|--building_type BUILDING_TYPE`: access raw building type stock data
    (`residential` and `commercial` datasets only)

  - `-C|--county COUNTY`: select county

  - `-D|--dataset {residential,commercial,industrial,agricultural,weather,total}`:
    select dataset (default `total`)

  - `-d|--debug`: enable debug logging and traceback on exceptions

  - `-f|--format {csv,gzip,zip,xlsx,pie,scatter,plot}`: specify output format

  - `-h|--help`: show this help message and exit

  - `-o|--output OUTPUT`: set output file name

  - `-p|--precision PRECISION`: specify output precision (default 3)

  - `-S|--state STATE`: select state

  - `-w|--warning`: enable warning messages from python

  - `-Y|--year YEAR`: select year (only used by the `weather` dataset; the
    load datasets return their 2018 reference data)

See https://www.eudoxys.com/loads for full documentation.

Description
-----------

`loads` estimates hourly electricity demand, in megawatts, for each county in
the United States, broken down by economic sector and driven by that county's
actual weather. It is intended for power-system planning studies that need a
realistic county load shape for a specific year, and it can sum county loads
onto network nodes (e.g., the WECC 240-bus model) with `loads.aggregate`.

Given a state and a county, `loads.total.Total` returns a data frame that is
expected to satisfy the following:

  1. **Reference-year sector breakdown.** By default (`samples=None`) the
     frame holds the 2018 training data: one row per hour of 2018 indexed by
     a UTC `timestamp`, the county's 2018 weather, and separate columns for
     residential, commercial, industrial, agricultural and transportation
     load (`elec_residential_MW`, ..., `elec_transportation_MW`).

  2. **Consistent totals.** In the training data `elec_total_MW` is the sum
     of the sector columns and excludes distributed generation.
     `elec_dg_MW` (rooftop solar and other distributed generation) is never
     positive, and `elec_net_MW = elec_total_MW + elec_dg_MW`.

  3. **Predictions for other periods.** Given a `date_range` and
     `samples=0`, the frame holds the weather variables used as inputs and
     a TSGAM prediction of one load column (`Y`, default `elec_total_MW`)
     for every hour of the range. With `samples=1` the prediction is replaced
     by one autoregressive sample, and with `samples>1` by the requested
     `percentile` of that many samples.

  4. **Weather response.** Predicted residential, commercial and total load
     follow the county's outdoor temperature and humidity for the requested
     period, and predicted distributed generation follows its direct and
     diffuse sunlight. Industrial and agricultural load do not depend on
     weather.

  5. **Repeatability.** Training data and the downloaded inputs are cached
     locally after the first run unless `refresh=True` is given. Predictions
     (`samples=0`) are deterministic; sampled results are not.

How the estimate is produced
----------------------------

  - Residential load uses NLR ResStock 2018 building-type load shapes, scaled
    by US Census housing-unit counts.

  - Commercial load uses NLR ComStock 2018 building-type load shapes, scaled
    by OpenEI commercial floor area.

  - Industrial and agricultural load spread each county's annual energy from
    NLR county inventories evenly over the year (a flat load shape).

  - Transportation is not yet modeled and is reported as zero.

  - The 2018 sector loads and the county's 2018 weather are used to train a
    time-series model (TSGAM). Loads for other periods are predicted from
    that period's weather, so a hotter summer produces more cooling load.
    `loads.estimator.Estimator` is a newer front end to the same kind of
    model that uses a single `"County ST"` location argument.

  - Calibration to published totals is a separate step.
    `loads.calibrate.Calibrate` shapes a panel of county (or node) loads so
    that it honors monthly state energy targets and regional peak ceilings,
    and `loads/wecc/wecc_estimate.py` rescales each county's monthly energy
    to its gross load, i.e., the EIA 861M retail sales allocated to it plus
    its distributed generation.

The same approach applies to non-electric energy (`nonelec_*` columns) where
the building-stock data provides it.

What is not promised
--------------------

  - Industrial and agricultural loads have no hourly, daily or seasonal shape
    and are not checked against EIA totals.

  - `Total` itself does not calibrate to EIA totals. Neither the training
    data nor the predictions are adjusted to reported state sales unless
    `loads.calibrate` (or another rescaling) is applied afterwards.

  - Results are only available for periods with weather data and have
    mostly been exercised for 2018-2022 in western (WECC) states.

  - Predictions and samples only contain the weather inputs and the one
    predicted column, not the full sector breakdown.

  - The first and last few hours of a prediction or sample are NaN (see
    `loads.total`).

Load data
---------

Load data frames generally contain any of the following, indexed by date/time:

  - `elec_baseload_MW`: electric end uses other than space cooling and
    heating, e.g., lighting, appliances, plug loads, refrigeration, pumps,
    and water heating.

  - `elec_cooling_MW`: electric space cooling end uses (compressors, cooling
    fans and pumps).

  - `elec_heating_MW`: electric space heating end uses (heaters, heat pumps,
    heating fans and pumps, supplemental heat).

  - `elec_total_MW`: total electric loads, i.e., base load plus cooling and
    heating loads.

  - `elec_dg_MW`: distributed generation, i.e., negative loads from sources
    such as rooftop photovoltaics.

  - `elec_net_MW`: net load, i.e., total including distributed generation.

  - `nonelec_baseload_MW`: non-electric (gas, propane, fuel oil, district,
    other fuel) end uses other than space cooling and heating, e.g., water
    heating, cooking and drying.

  - `nonelec_cooling_MW`: non-electric space cooling end uses (e.g.,
    district cooling).

  - `nonelec_heating_MW`: non-electric space heating end uses (e.g., gas,
    propane, fuel oil and wood heating).

  - `nonelec_total_MW`: total non-electric loads, i.e., non-electric base
    load plus cooling and heating loads.

`loads.total.Total` instead reports electric load by sector
(`elec_residential_MW`, `elec_commercial_MW`, `elec_industrial_MW`,
`elec_agricultural_MW`, `elec_transportation_MW`) together with
`elec_total_MW`, `elec_dg_MW`, `elec_net_MW` and the weather columns from
`weather.Weather` (e.g., `temperature_degF`, `humidity_pc`, `global_Wpms`,
`direct_Wpms`, `diffuse_Wpms`).

Not all data frames will contain all these columns.

Package architecture
--------------------

```mermaid
---
config:
  flowchart:
    wrappingWidth: 700
    rankSpacing: 40
    nodeSpacing: 20
---
%% Data flow in github.com/eudoxys/loads
%% Orange dashed cylinders = external sources fetched over the network
%% Grey = files bundled in the repo · Green = outputs
flowchart TB

    NOTE["<b>eudoxys/loads</b> data flow · all modules cache results locally via <b>eudoxys/cache</b>"]

    %% ---------- all external sources, two rows ----------
    %% Split over two rows to keep the diagram narrow. The upper row holds the
    %% sources feeding the deepest consumers (their lines run down the sides);
    %% the lower row holds the sources feeding the sector models directly below.
    %% Declaration order is tuned for Mermaid 11 (which pdoc loads) to minimize
    %% the width; changing the order can change the layout substantially.
    subgraph EXT["EXTERNAL DATA SOURCES"]
        direction LR
        NODES[("wecc240 GitHub<br/>county_nodes.csv")]
        EIA[("EIA Form 861M<br/>/ HS861M<br/>via eudoxys/eia")]
        FIPS[("eudoxys/fips<br/>county metadata<br/>(used everywhere)")]
        GEOJSON[("Plotly county<br/>GeoJSON")]
        WECCGIS[("wecc240 GitHub<br/>node GIS, Canada,<br/>Mexico")]
        WX[("NLR weather<br/>via eudoxys/weather")]
        OEDI_RES[("NLR ResStock<br/>OEDI S3")]
        CENSUS[("US Census<br/>housing units")]
        OEDI_COM[("NLR ComStock<br/>OEDI S3")]
        OPENEI[("OpenEI #906<br/>floor area")]
        NLR97[("NLR #97<br/>industry &<br/>agriculture")]
    end

    %% Pin the upper row of sources just below the note (duplicate invisible
    %% links outweigh each source's outgoing edges so the layout won't pull it down).
    NOTE ~~~ NODES & NODES
    NOTE ~~~ EIA & EIA & EIA
    NOTE ~~~ FIPS
    NOTE ~~~ GEOJSON & GEOJSON
    NOTE ~~~ WECCGIS & WECCGIS
    NOTE ~~~ WX & WX

    %% Pin the lower row of sources just below the upper row.
    EIA ~~~ OEDI_RES & OEDI_RES
    EIA ~~~ CENSUS & CENSUS
    WX ~~~ OEDI_COM & OEDI_COM
    WX ~~~ OPENEI & OPENEI
    WX ~~~ NLR97 & NLR97 & NLR97

    %% ---------- sector models ----------
    RESID["residential.py"]
    COMM["commercial.py"]
    IND["industry.py"]
    AGR["agriculture.py"]
    TRANS["transportation.py<br/>(not implemented)"]

    OEDI_RES -- resstock.py --> RESID
    CENSUS -- units.py --> RESID
    OEDI_COM -- comstock.py --> COMM
    OPENEI -- floorarea.py --> COMM
    NLR97 --> IND
    NLR97 --> AGR

    %% ---------- total load model ----------
    subgraph TOTALG["total.py · Total"]
        direction TB
        FIT["TSGAM fit<br/>(nimish/estimator)"]
        SAMPLE["Sample / predict<br/>hourly county load"]
        NET["elec_total_MW<br/>elec_dg_MW · elec_net_MW"]
        FIT --> SAMPLE --> NET
    end

    CAL(["calibrate.py · Calibrate<br/>state energy & regional peaks"])
    NET --> CAL

    RESID --> FIT
    COMM --> FIT
    IND --> FIT
    AGR --> FIT
    TRANS -.-> FIT
    WX --> FIT

    DGFILE["wecc/county_dg.csv.gz<br/>(built offline, see below)"]
    DG["dgen.py · DG<br/>county solar"]

    EIA -- "solar" --> DG
    DGFILE --> DG
    EIA -- "state sales" --> CAL
    DG --> CAL

    %% ---------- offline build of county DG ----------
    subgraph BUILD["Offline build · dgen.compile()"]
        direction TB
        ENERGY["energy.py · Energy<br/>monthly MWh"]
        DGEN_RAW["wecc/dgen.csv.gz<br/>NLR dGen nodal DG"]
        MWH_CF["wecc/county_mwh.csv<br/>wecc/county_cf.csv"]
        COMPILE["nodal → county DG"]
        DGOUT["wecc/county_dg.csv.gz"]
        ENERGY --> COMPILE
        ENERGY --> MWH_CF
        DGEN_RAW --> COMPILE
        COMPILE --> DGOUT
    end
    NET -. "Energy() calls Total()" .-> ENERGY
    NODES --> COMPILE

    %% ---------- downstream uses ----------
    CLUSTER["cluster.py<br/>explore_clusters_marimo.py"]
    CLUSTERS["clusters.csv · configs.csv"]
    EVAL(["tsgam_evaluate.py<br/>evaluate_lag.py"])
    CLI(["cli.py · loads command<br/>Python API"])
    AGG(["aggregate.py<br/>WECC 240 node loads"])

    GEOJSON --> CLUSTER
    NET --> CLUSTER
    CLUSTER --> CLUSTERS --> EVAL
    NET --> CLI
    NET --> AGG
    WECCGIS --> AGG

    %% ---------- styles ----------
    classDef external fill:#fde7d2,stroke:#d9480f,stroke-width:2px,stroke-dasharray:5 3,color:#5c2200
    classDef bundled fill:#eceff1,stroke:#607d8b,color:#263238
    classDef output fill:#e8f5e9,stroke:#2e7d32,color:#1b4d20
    classDef note fill:#fffde7,stroke:#c9b458,color:#4a4000
    class FIPS,GEOJSON,EIA,OEDI_RES,CENSUS,OEDI_COM,OPENEI,NLR97,WX,WECCGIS,NODES external
    class DGEN_RAW,DGFILE,DGOUT,MWH_CF,CLUSTERS bundled
    class NET,CAL,CLI,AGG,EVAL output
    class NOTE note
    style EXT fill:#fff8f2,stroke:#d9480f,stroke-width:2px
```
  - `loads.aggregate`: load aggregation by geography

  - `loads.agriculture`: 2019 agricultural load data

  - `loads.calibrate`: net-load shaping to state energy and regional peak targets

  - `loads.cast`: weather-based back/forecast of a 2018 load to another year

  - `loads.cli`: command line interface

  - `loads.cluster`: SVD and k-means clustering of county load shapes

  - `loads.commercial`: 2018 commercial building compiled load data

  - `loads.comstock`: 2018 commercial building end-use load data

  - `loads.dgen`: county distributed generation data

  - `loads.energy`: County and state-level periodic energy consumption

  - `loads.estimator`: TSGAM load estimator for target years

  - `loads.floorarea`: 2019 commercial building floor area data

  - `loads.industry`: 2019 industrial load data

  - `loads.residential`: 2018 residential building compiled load data

  - `loads.resstock`: 2018 residential building end-use load data

  - `loads.total`: total loads by sector

  - `loads.transportation`: transportation load data (not implemented)

  - `loads.units`: 2020-2024 residential housing units data

Notebooks and scripts
---------------------

The following `marimo` notebooks and scripts are available to review the
results of applying the `loads` model tools on the WECC system.

  - `review_loads.py` reviews the load data of a county

  - `evaluate_lag.py` evaluates the exogenous lag window of the cluster
    medoid TSGAM configurations in `configs.csv`

  - `tsgam_evaluate.py` searches for the best TSGAM configuration of each
    cluster medoid

  - `wecc/wecc_estimate.py` generates the hourly 2018-2022 load estimate of
    every WECC county (`wecc/wecc_estimate.csv.gz`)

  - `_explore/` contains notebooks and scripts used to choose the cluster
    configuration, the estimator harmonics and the calibration weights (see
    `_explore/README.md`)

  - `_review/review_wecc_estimate_marimo.py` displays the WECC county load
    estimate and `_review/review_commercial_marimo.py` reviews the commercial
    load data

  - `_validate/validate_estimator_marimo.py` validates the estimator (see
    `_validate/README.md`)

Example
-------

The following command plots the 2018 sector loads for Alameda County CA:

    loads plot -S=CA -C=Alameda

Caveats
-------

  - Most of the data comes from online sources that are cached locally to help
    with performance. However, some of the initial downloads can take several
    minutes to complete before being cached.

  - Some residential and commercial building types are not available in some
    counties. In such cases a zero data frame is constructed (and an error is
    logged if the download failed for a reason other than missing data).

  - Weather data requires NSRDB credentials in `~/.nsrdb/credentials.json`
    (see https://www.eudoxys.com/weather).

Package information
-------------------

  - Source code: https://github.com/eudoxys/loads

  - Documentation: https://www.eudoxys.com/loads

  - Issues: https://github.com/eudoxys/loads/issues

  - License: https://github.com/eudoxys/loads/blob/main/LICENSE

  - Dependencies:

    - [cvxpy](https://pypi.org/project/cvxpy/)
    - [h5pyd](https://pypi.org/project/h5pyd/)
    - [marimo](https://pypi.org/project/marimo/)
    - [matplotlib](https://pypi.org/project/matplotlib/)
    - [numpy](https://pypi.org/project/numpy/)
    - [openpyxl](https://pypi.org/project/openpyxl/)
    - [pandas](https://pypi.org/project/pandas/)
    - [plotly](https://pypi.org/project/plotly/)
    - [pytz](https://pypi.org/project/pytz/)
    - [pyxlsb](https://pypi.org/project/pyxlsb/)
    - [requests](https://pypi.org/project/requests/)
    - [scikit-learn](https://pypi.org/project/scikit-learn/)
    - [spcqe](https://pypi.org/project/spcqe/)
    - [tsgam_estimator](https://github.com/nimish/estimator/)
    - [cache](https://github.com/eudoxys/cache/)
    - [eia](https://github.com/eudoxys/eia/)
    - [fips](https://github.com/eudoxys/fips/)
    - [geohash](https://github.com/eudoxys/geohash/)
    - [weather](https://github.com/eudoxys/weather/)
"""

from loads.aggregate import Aggregator
from loads.agriculture import Agriculture
from loads.calibrate import Calibrate
from loads.cli import main
from loads.cluster import Cluster
from loads.commercial import Commercial
from loads.comstock import COMstock
from loads.estimator import Estimator
from loads.dgen import DG
from loads.energy import Energy
from loads.floorarea import Floorarea
from loads.industry import Industry
from loads.residential import Residential
from loads.resstock import RESstock
from loads.total import Total
from loads.transportation import Transportation
from loads.units import Units

