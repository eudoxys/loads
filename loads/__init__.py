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

`loads` estimates hourly electricity demand, in megawatts, for each county in
the United States, broken down by economic sector and driven by that county's
actual weather. It is intended for power-system planning studies that need a
realistic county load shape for a specific year, and it can sum county loads
onto network nodes (e.g., the WECC 240-bus model) with `loads.aggregate`.

Given a state, a county, and a year or date range, `loads.total.Total` returns
a data frame that is expected to satisfy the following:

  1. **Complete hourly coverage.** One row per hour of the requested period,
     indexed by a UTC `timestamp` (8760 rows for a normal year, 8784 for a
     leap year).

  2. **Sector breakdown.** Separate columns for residential, commercial,
     industrial, agricultural and transportation load
     (`elec_residential_MW`, ..., `elec_transportation_MW`), plus the weather
     used to produce them.

  3. **Consistent totals.** `elec_total_MW` is the sum of the sector columns.
     `elec_dg_MW` (rooftop solar and other distributed generation) is never
     positive. `elec_net_MW = elec_total_MW + elec_dg_MW`.

  4. **Weather response.** Residential and commercial load follow the
     county's outdoor temperature and humidity for the requested period, and
     distributed generation follows its direct and diffuse sunlight.
     Industrial and agricultural load do not depend on weather.

  5. **Agreement with reported state totals.** For the reference year (2018),
     residential and commercial energy summed over every county in a state
     equals that state's annual EIA Form 861M retail sales for each sector.
     Distributed generation summed the same way equals the state's
     EIA-reported small-scale solar output.

  6. **Repeatability.** The same request returns the same result; results are
     cached locally after the first run unless `refresh=True` is given.

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
    time-series model (TSGAM). Loads for other years are predicted from that
    year's weather, so a hotter summer produces more cooling load.

  - Residential and commercial loads and distributed generation are scaled to
    match the state totals EIA reports for 2018 (item 5 above).

The same approach applies to non-electric energy (`nonelec_*` columns) where
the building-stock data provides it.

What is not promised
--------------------

  - Industrial and agricultural loads have no hourly, daily or seasonal shape
    and are not checked against EIA totals.

  - Predicted years are not re-calibrated to that year's EIA totals; they
    inherit the 2018 calibration.

  - Results are only available for years with weather data and have mostly
    been exercised for 2018-2022 in western (WECC) states.

  - Calibrating any one county requires computing every county in its state
    first, which can take a long time for states with many counties.

  - When `samples` is 1 or more, the first and last few hours of a sampled
    series may be missing (see `loads.total`).

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
        ENERGY --> COMPILE
        ENERGY --> MWH_CF
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

  - Item 3 of the Description may not hold at present. `Total` computes
    `elec_total_MW` by summing every column ending in `_MW`, which at that
    point already includes `elec_dg_MW`. DG therefore appears to be counted in
    the total and then subtracted again when `elec_net_MW` is computed (see
    `loads.total.Total._get_training`).

  - Item 1 of the Description does not hold when sampling. With `samples` of
    1 or more, the leading and trailing lag hours of each sampled series are
    set to NaN.

  - The "Load data" section describes `elec_baseload_MW` (and
    `nonelec_baseload_MW`) as dependent on outdoor air temperature and solar
    gains, which describes a weather-driven load rather than a base load.
    The definitions should be checked against how the columns are computed.

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
from loads.normalize import Normalize
from loads.residential import Residential
from loads.resstock import RESstock
from loads.total import Total
from loads.transportation import Transportation
from loads.units import Units

