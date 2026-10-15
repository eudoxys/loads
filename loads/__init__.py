"""Electric load data accessors

Syntax
------

    loads {print,plot} [-S STATE] [-C COUNTY] [-B BUILDING_TYPE] [-Y YEAR]
          [-D {residential,commercial,industrial,agricultural,weather}] 
          [-h] [-o OUTPUT] [-f {csv,gzip,zip,xlsx,pie,scatter,plot}] [-p PRECISION] 
          [-w] [-d]

Positional arguments
--------------------

  - `help`: open online documentation

  - `info`: get package information

  - `print`: output text

  - `plot`: output graphics

  - `viewer`: open load browser

Optional arguments
------------------

  - `-B|--building_type BUILDING_TYPE`: access raw building type stock data

  - `-C|--county COUNTY`: select county

  - `-D|--dataset {residential,commercial,industrial,agricultural,public,weather}`: select dataset

  - `-d|--debug`: enable debug traceback on exceptions

  - `--format {csv,gzip,zip,xlsx}`: specify output format

  - `-h|--help`: show this help message and exit

  - `-o|--output OUTPUT`: set output file name

  - `--precision PRECISION`: specify output precision

  - `-S|--state STATE`: select state

  - `-w|--warning`: enable warning messages from python

  - `-Y|--year YEAR`: select year

See https://www.eudoxys.com/loads for full documentation.

Description
-----------

The `loads` package retrieves data for the following sectors:

  - `residential`: based on data from NREL RESstock

  - `commercial`: based on data from NREL COMstock

  - `industrial`: based on data from NREL's industrial loads inventory

  - `agricultural`: based on data from NREL's agricultural loads inventory

In addition corresponding `weather` data is available for the residential and
commercial sector loads that weather sensitive

Load data
---------

Load data frames generally contain any of the following, indexed by date/time:

  - `elec_baseload_MW`: electric loads which are dependent on outdoor air
    temperature and solar gains over all conditions.

  - `elec_cooling_MW`: electric loads which are dependent on outdoor air
    temperature only when cooling is required.

  - `elec_heating_MW`: electric loads which are dependent on outdoor air
    temperature only when heating is required.

  - `elec_total_MW`: total electric loads, i.g., base load plus cooling and
    heating loads.

  - `elec_dg_MW`: distribution generation, i.e., negative loads from sources
    such as rooftop photovoltaics and batteries that are discharging.

  - `elec_net_MW`: net load, i.e., total including distributed generation.

  - `nonelec_baseload_MW`: non-electric loads which are dependent on outdoor air
    temperature and solar gains over all conditions.

  - `nonelec_cooling_MW`: non-electric loads which are dependent on outdoor air
    temperature only when cooling is required.

  - `nonelec_heating_MW`: non-electric loads which are dependent on outdoor air
    temperature only when heating is required.

  - `nonelec_total_MW`: total non-electric loads, i.g., non-electric base load plus cooling and
    heating loads.

Not all data frames will contain all these columns. Columns that are all zeros may be omitted.

Package architecture
--------------------

```mermaid
---
config:
  flowchart:
    wrappingWidth: 700
    rankSpacing: 40
---
%% Data flow in github.com/eudoxys/loads
%% Orange dashed cylinders = external sources fetched over the network
%% Grey = files bundled in the repo · Green = outputs
flowchart TB

    NOTE["<b>eudoxys/loads</b> data flow · all modules cache results locally via <b>eudoxys/cache</b>"]

    %% ---------- all external sources, one row ----------
    %% Ordered left→right to match where their consumers sit; sources feeding
    %% the deepest consumers are at the outer edges so their lines run down the sides.
    subgraph EXT["EXTERNAL DATA SOURCES"]
        direction LR
        FIPS[("eudoxys/fips<br/>county metadata<br/>(used everywhere)")]
        GEOJSON[("Plotly county<br/>GeoJSON")]
        EIA[("EIA Form 861M<br/>/ HS861M<br/>via eudoxys/eia")]
        OEDI_RES[("NLR ResStock<br/>OEDI S3")]
        CENSUS[("US Census<br/>housing units")]
        OEDI_COM[("NLR ComStock<br/>OEDI S3")]
        OPENEI[("OpenEI #906<br/>floor area")]
        NLR97[("NLR #97<br/>industry &<br/>agriculture")]
        WX[("NLR weather<br/>via eudoxys/weather")]
        WECCGIS[("wecc240 GitHub<br/>node GIS, Canada,<br/>Mexico")]
        NODES[("wecc240 GitHub<br/>county_nodes.csv")]
    end

    %% Pin every external source to the top row (duplicate invisible links
    %% outweigh each source's outgoing edges so the layout won't pull it down).
    NOTE ~~~ FIPS
    NOTE ~~~ GEOJSON & GEOJSON
    NOTE ~~~ EIA & EIA & EIA
    NOTE ~~~ OEDI_RES & OEDI_RES
    NOTE ~~~ CENSUS & CENSUS
    NOTE ~~~ OEDI_COM & OEDI_COM
    NOTE ~~~ OPENEI & OPENEI
    NOTE ~~~ NLR97 & NLR97 & NLR97
    NOTE ~~~ WX & WX
    NOTE ~~~ WECCGIS & WECCGIS
    NOTE ~~~ NODES & NODES

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
        CAL["calibrate.py · Calibrate"]
        NET["elec_total_MW<br/>elec_dg_MW · elec_net_MW"]
        FIT --> SAMPLE --> CAL --> NET
    end

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
        ENERGY --> MWH_CF
        ENERGY --> COMPILE
        DGEN_RAW --> COMPILE
        COMPILE --> DGOUT
    end
    NET -. "Energy() calls Total()" .-> ENERGY
    NODES --> COMPILE

    %% ---------- downstream uses ----------
    CLUSTER["cluster.py<br/>review_clusters.py"]
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
    class NET,CLI,AGG,EVAL output
    class NOTE note
    style EXT fill:#fff8f2,stroke:#d9480f,stroke-width:2px
```
  - `loads.aggregate`: load aggregation by geography

  - `loads.agriculture`: 2019 agricultural load data

  - `loads.calibrate`: load calibration to energy use

  - `loads.cli`: command line interface

  - `loads.commercial`: 2018 commercial building compiled load data

  - `loads.comstock`: 2018 commercial building end-use load data

  - `loads.energy`: County and state-level periodic energy consumption

  - `loads.floorarea`: 2020-era commercial building floor area data

  - `loads.industry`: 2019 industrial load data

  - `loads.residential`: 2018 residential building compiled load data

  - `loads.resstock`: 2018 residential building end-use load data

  - `loads.total`: total loads by sector

  - `loads.transportation`: 2019 transportation load data

  - `loads.units`: 2020-era residential units data

Notebooks
---------

The following `marimo` notebooks are available to review the results of
applying the `loads` model tools on the WECC system.

  - `review_clusters.py` provides a notebook to review the results of county
    clustering

  - `review_loads.py` provides a notebook to review the load data

Example
-------

The following command plots the loads for Alemeda County CA in 2020:

    loads plot -S=CA -C=Alameda -Y=2020

Caveats
-------

  - Most of the data comes from online sources that are cached locally to help
    with performance. However, some of the initial downloads can take a several
    minutes to complete before being cached.

  - Some residential and commercial building types are not available in some
    counties. In such cases a warning is output and a zero dataframe is
    constructed.

Package information
-------------------

  - Source code: https://github.com/eudoxys/loads

  - Documentation: https://www.eudoxys.com/loads

  - Issues: https://github.com/eudoxys/loads/issues

  - License: https://github.com/eudoxys/loads/blob/main/LICENSE

  - Dependencies: 

    - [h5pyd](https://pypi.org/project/h5pyd/)
    - [marimo](https://pypi.org/project/marimo/)
    - [matplotlib](https://pypi.org/project/matplotlib/)
    - [openpyxl](https://pypi.org/project/openpyxl/)
    - [pandas](https://pypi.org/project/pandas/)
    - [plotly](https://pypi.org/project/plotly/)
    - [pytz](https://pypi.org/project/pytz/)
    - [pyxlsb](https://pypi.org/project/pyxlsb/)
    - [requests](https://pypi.org/project/requests/)
    - [cache](https://github.com/eudoxys/cache/)
    - [eia](https://github.com/eudoxys/eia/)
    - [fips](https://github.com/eudoxys/fips/)
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

