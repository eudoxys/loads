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
flowchart TD

    NREL --> RESstock

    Census --> Units

    OpenEI --> Floorarea

    RESstock --> Residential
    Units --> Residential


    NREL ---> Industry

    NREL ---> Agriculture

    NREL ---> Weather

    NREL --> COMstock

    COMstock --> Commercial
    Floorarea --> Commercial

    Residential --> Estimate
    Industry --> Estimate
    Agriculture --> Estimate
    Weather --> Estimate
    Commercial --> Estimate

    Estimate --> Calibrate
```

  - `loads.agriculture`: 2019 agricultural load data

  - `loads.cache`: manage local data cache

  - `loads.calibrate`: load calibration to energy use

  - `loads.cli`: command line interface

  - `loads.commercial`: 2018 commercial building compiled load data

  - `loads.comstock`: 2018 commercial building end-use load data

  - `loads.floorarea`: 2020-era commercial building floor area data

  - `loads.industry`: 2019 industrial load data

  - `loads.residential`: 2018 residential building compiled load data

  - `loads.resstock`: 2018 residential building end-use load data

  - `loads.units`: 2020-era residential units data

  - `loads.weather`: 2018 reference weather data

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

from loads.agriculture import Agriculture
from loads.calibrate import Calibrate
from loads.cli import main
from loads.comstock import COMstock
from loads.commercial import Commercial
from loads.floorarea import Floorarea
from loads.industry import Industry
from loads.resstock import RESstock
from loads.residential import Residential
from loads.total import Total
from loads.units import Units

