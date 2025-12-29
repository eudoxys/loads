"""Electric load data accessors

# Syntax

  `loads [-h] [-y YEAR] [-o OUTPUT] [--building_type BUILDING_TYPE]
  [--format {csv,gzip,zip,xlsx}] [--precision PRECISION] [--warning] [--debug] 
  state county {residential,commercial,industrial,agricultural,public,weather}`

## Positional arguments

- `state`

- `county`

- `{residential,commercial,industrial,agricultural,public,weather}`O

## Option arguments

-  `-h`, `--help`           show this help message and exit

- `-y`, `--year YEAR`       set load model year

- `-o`, `--output OUTPUT`   set output file name

- `--building_type BUILDING_TYPE`
                            access raw building type stock data

- `--format {csv,gzip,zip,xlsx}`
                            specify output format

- `--precision PRECISION`
                            specify output precision

- `--warning`.              enable warning messages from python

- `--debug`                 enable debug traceback on exceptions

See https://www.eudoxys.com/loads for documentation.

# Description

The `loads` package retrieves data for the following sectors:

- `residential`: based on data from NREL RESstock

- `commercial`: based on data from NREL COMstock

- `industrial`: based on data from NREL's industrial loads inventory

- `agricultural`: based on data from NREL's agricultural loads inventory

In addition corresponding `weather` data is available for the residential and
commercial sector loads that weather sensitive

## Load data

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

# Package architecture

```mermaid
flowchart TD

    NREL --> RESstock

    Census --> Units

    OpenEI --> Floorarea

    RESstock --> Residential
    Units --> Residential


    NREL --> Industry

    NREL --> Agriculture

    NREL --> Weather

    NREL --> COMstock

    COMstock --> Commercial
    Floorarea --> Commercial
```

# Example

    loads CA Alameda residential

# Caveats

- Most of the data comes from online sources that are cached locally to help
  with performance. However, some of the initial downloads can take a several
  minutes to complete before being cached.

- Some residential and commercial building types are not available in some
  counties. In such cases a warning is output and a zero dataframe is
  constructed.

# Package information

- Source code: https://github.com/eudoxys/loads

- Documentation: https://www.eudoxys.com/loads

- Issues: https://github.com/eudoxys/loads/issues

- License: https://github.com/eudoxys/loads/blob/main/LICENSE

- Dependencies: 

  - [pandas](https://pypi.org/project/pandas/)
  - [openpyxl](https://pypi.org/project/openpyxl/)
  - [pyxlsb](https://pypi.org/project/pyxlsb/)
  - [requests](https://pypi.org/project/requests/)
  - [pytz](https://pypi.org/project/pytz/)
  - [fips](https://github.com/eudoxys/fips)

"""

from loads.agriculture import Agriculture
from loads.cast import Cast
from loads.cli import main
from loads.comstock import COMstock
from loads.floorarea import Floorarea
from loads.industry import Industry
from loads.residential import Residential
from loads.resstock import RESstock
from loads.units import Units
from loads.weather import Weather

import loads.cache

