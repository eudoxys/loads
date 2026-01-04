# pylint: disable=line-too-long
"""Electric loads data accessor

Generates electric load model for residential, commercial, industrial,
agricultural, and public sectors. Two types of data frame are generated
depending on whether `building_type` is specified.

If `building_type` is specified, then the raw end-use data for that building
type is returned, the columns of which depend on the building type.  If
`building_type` is not specified, then the compiled end-use data for the
entire sector is returned in columns of MW electric and non-electric base,
cooling, heating, total, distributed generation, and net loads.

# Examples

To print the raw residential single-family detached house loads in Alameda
County CA as a table, the command

    loads CA Alameda residential --building_type=RSD

outputs the following

                               elec_bathfan  elec_ceilingfan  elec_dryer  elec_washer  elec_cooking  elec_cooling  elec_dishwasher  elec_holidaylight  elec_extlighting  elec_extrarefrigerator  elec_coolingfan  elec_heatingfan  elec_freezer  elec_garagelighting  elec_heating  elec_heatingsupplement  elec_hottubheater  elec_hottubpump  elec_housefan  elec_interiorlighting  elec_plugs  elec_poolheater  elec_poolpump  elec_coolingpump  elec_heatingpump  elec_pv  elec_rangefan  elec_recircpump  elec_refrigerator  elec_total  elec_vehicle  elec_watersystems  elec_wellpump  oil_heating  oil_total  oil_watersystems  gas_dryer  gas_cooking  gas_fireplace  gas_grill  gas_heating  gas_hottubheater  gas_lighting  gas_poolheater  gas_total  gas_watersystems  lng_dryer  lng_range  lng_heating  lng_total  lng_watersystems     total  wood_heating  wood_total        units
    2018-01-01 00:00:00+00:00         0.591              0.0      91.735        4.494        39.677        13.872            7.110                0.0             9.518                  17.145            3.398            2.654         6.775                1.998        19.155                     0.0             20.248           38.781            0.0                138.807     352.836            2.134         45.367               0.0             0.001  -30.636          2.852              0.0             48.158     898.648           0.0             24.917          6.424          0.0      0.000             0.000     46.692      118.086          8.053      7.378      132.501            43.160         0.854          22.473    856.121           476.925        0.0      0.000        0.465      8.426             7.961  1763.196           0.0         0.0  1253270.056
    2018-01-01 01:00:00+00:00         0.974              0.0      87.019        4.141        40.727         9.286            6.756                0.0            12.934                  18.704            2.449            3.869         7.391                2.715        22.761                     0.0             19.605           37.550            0.0                212.416     395.534            1.326         28.201               0.0             0.002   -0.000          4.336              0.0             52.536    1004.794           0.0             25.424          8.137          0.0      1.305             1.305     66.496      163.327         10.200     10.798      210.654            41.790         1.081          13.970   1061.623           543.306        0.0      0.000        1.331      7.343             6.012  2075.065           0.0         0.0  1253270.056
    2018-01-01 02:00:00+00:00         1.356              0.0      66.788        5.373        51.262         4.514           13.542                0.0            15.375                  19.483            1.342            6.934         7.698                3.227        37.751                     0.0             10.928           20.929            0.0                296.956     429.803            0.750         15.940               0.0             0.005   -0.000          3.617              0.0             54.725    1108.728           0.0             31.007          9.422          0.0      0.000             0.000     49.159      200.504         11.811      7.713      387.342            23.293         1.252           7.896   1266.874           577.905        0.0      0.000        1.439     27.607            26.168  2403.209           0.0         0.0  1253270.056
    2018-01-01 03:00:00+00:00         1.600              0.0      55.489        6.329        36.005         3.073           18.098                0.0            16.351                  18.704            0.699           11.241         7.391                3.432        60.654                     0.0              9.803           18.775            0.0                305.999     418.660            0.461          9.809               0.0             0.009   -0.000          2.064              0.0             52.536    1093.182           0.0             25.152         10.849          0.0      1.323             1.323     58.636      130.942         13.600      4.695      630.644            20.895         1.442           4.859   1551.857           686.143        0.0      0.000        4.986     15.021            10.035  2661.383           0.0         0.0  1253270.056
    ...
    2018-12-31 20:00:00+00:00         0.475              0.0      64.666        5.024        31.640         7.413            5.326                0.0             5.857                  16.366            1.506            9.037         6.467                1.229        48.037                     0.0              2.250            4.309            0.0                 90.326     324.885            6.920        147.137               0.0             0.009 -197.184          1.693              0.0             45.969     862.904           0.0             31.795          4.568          0.0      0.000             0.000     67.763       98.033          5.726      2.817      501.342             4.796         0.607          72.887   1328.836           574.865        0.0      2.467        2.990     13.087             7.630  2204.827           0.0         0.0  1253270.056
    2018-12-31 21:00:00+00:00         0.487              0.0      88.348        4.384        24.068         9.498            2.763                0.0             6.833                  16.366            1.862            6.371         6.467                1.434        33.251                     0.0              2.250            4.309            0.0                 86.332     319.859            5.190        110.353               0.0             0.004 -186.023          1.669              0.0             45.969     811.211           0.0             28.575          4.568          0.0      0.000             0.000     63.494       70.822          5.726      2.549      343.189             4.796         0.607          54.665   1063.982           518.134        0.0      0.000        1.846      9.892             8.046  1885.085           0.0         0.0  1253270.056
    2018-12-31 22:00:00+00:00         0.359              0.0      62.863        4.585        22.521        12.094            2.340                0.0             7.565                  16.366            2.691            4.382         6.467                1.588        31.096                     0.0              3.857            7.387            0.0                 90.324     318.674            4.325         91.961               0.0             0.003 -155.361          2.133              0.0             45.969     768.840           0.0             24.723          4.568          0.0      0.000             0.000     36.104       83.604          5.726      3.286      234.099             8.221         0.607          45.554    914.240           497.037        0.0      0.000        0.959      7.457             6.498  1690.537           0.0         0.0  1253270.056
    2018-12-31 23:00:00+00:00         0.278              0.0      53.031        4.572        21.179        18.084            3.583                0.0             7.809                  15.976            4.070            2.242         6.313                1.639        18.060                     0.0              9.321           17.852            0.0                106.069     331.294            3.518         74.795               0.0             0.002 -108.314          1.229              0.0             44.875     769.450           0.0             18.951          4.711          0.0      0.000             0.000     43.263       67.262          5.905      3.957      123.962            19.867         0.626          37.051    760.953           459.058        0.0      0.000        0.525      8.253             7.728  1538.656           0.0         0.0  1253270.056

To get the compiled residential loads in Alameda County CA in CSV format, the command

    loads CA Alameda residential --format=csv

outputs the following

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

# Caveats

* Compiling data can be time consuming. To help with performance data is cached
  locally in the package library. 
"""
# pylint: enable=line-too-long

import sys
import argparse
import warnings

import pandas as pd

# pylint: disable=unused-import
from loads.resstock import RESstock
from loads.residential import Residential
from loads.comstock import COMstock
from loads.commercial import Commercial
from loads.industry import Industry
from loads.agriculture import Agriculture
from loads.weather import Weather

E_OK = 0
"""Exit code on success"""

E_FAILED = 1
"""Exit code on failure"""

E_SYNTAX = 2
"""Exit code on syntax error"""

def main(*args:list[str]) -> int:
    """RESstock form accessor main command line processor

    # Argument

    - `*args`: command line arguments (`None` is `sys.argv`)

    # Returns

    - `int`: return/exit code
    """
    # pylint: disable=too-many-return-statements,too-many-branches
    try:

        # support direct call to main
        if args:
            sys.argv = [__file__] + list(args)

        # setup command line parser
        parser = argparse.ArgumentParser(
            prog="loads",
            description="Electric loads data accessor",
            epilog="See https://www.eudoxys.com/loads for documentation. ",
            )

        parser.add_argument("command",
            choices=["print","plot"]
            )
        parser.add_argument("-S","--state")
        parser.add_argument("-C","--county")
        parser.add_argument("-D","--dataset",
            choices=["residential","commercial","industrial","agricultural","weather"]
            )
        parser.add_argument("-Y","--year",
            type=int,
            help="set load model year (default 2018)")
        parser.add_argument("-o","--output",
            help="set output file name")
        parser.add_argument("-B","--building_type",
            help="access raw building type stock data (residential and commercial only)")
        parser.add_argument("-f","--format",
            choices=["csv","gzip","zip","xlsx","pie","scatter","plot"],
            help="specify output format (depends on command)")
        parser.add_argument("-p","--precision",
            type=int,
            default=3,
            help="specify output precision (default 3)"
            )
        parser.add_argument("-w","--warning",
            action="store_true",
            help="enable warning messages from python")
        parser.add_argument("-d","--debug",
            action="store_true",
            help="enable debug traceback on exceptions")

        # parse arguments
        args = parser.parse_args()

        # setup warning handling
        if not args.warning:
            warnings.showwarning = lambda *x:print(
                f"WARNING [{__package__}]:",
                x[0],
                flush=True,
                file=sys.stderr,
                )

        # get data
        match args.dataset:
 
            case "residential":
                source = (RESstock if args.building_type else Residential)
                kwargs = source.makeargs(**vars(args))
                data = source(**kwargs).round(args.precision)
 
            case "commercial":
                source = (COMstock if args.building_type else Commercial)
                kwargs = source.makeargs(**vars(args))
                data = source(**kwargs).round(args.precision)
 
            case "industrial":
                kwargs = Industry.makeargs(**vars(args))
                data = Industry(**kwargs).round(args.precision)
 
            case "agricultural":
                kwargs = Agriculture.makeargs(**vars(args))
                data = Agriculture(**kwargs).round(args.precision)
 
            case "weather":
                kwargs = Weather.makeargs(**vars(args))
                data = Weather(**kwargs).round(args.precision)
 
            case None:
                data = None
                for source in [Residential,Commercial,Industry,Agriculture]:
                    kwargs = source.makeargs(**vars(args))
                    tmp = source(**kwargs)
                    if data is None:
                        data = source(**kwargs)
                    elif not tmp.index.name is None:
                        tmp = source(**kwargs)
                        data += tmp
                    else:
                        for key,value in tmp.iterrows():
                            data[key] += value[tmp.columns[0]]

            case "_":
                raise ValueError(f"{args.sector=} is invalid")

        # handle default output
        if args.output is None:
            if args.format is None:
                pd.options.display.max_rows = None
                pd.options.display.width = None
                pd.options.display.max_columns = None
                print(data)
            elif args.format == "csv":
                print(data.to_csv())
            else:
                raise ValueError(f"{args.format} if not valid for this output stream")
            return E_OK

        # handle CSV output
        if args.output.endswith(".csv") or args.format == "csv":
            data.to_csv(args.output)
            return E_OK

        # handle GZIP output
        if args.output.endswith(".csv.gz") or args.format == "gzip":
            data.to_csv(args.output,compression="gzip")
            return E_OK

        # handle ZIP output
        if args.output.endswith(".csv.zip") or args.format == "zip":
            data.to_csv(args.output,compression="zip")
            return E_OK

        # handle XLSX output
        if args.output.endswith(".xlsx") or args.format == "xlsx":
            data.to_excel(args.output,
                sheet_name="Form861",
                merge_cells=False)
            return E_OK

        raise ValueError(f"output format '{args.format}' for '{args.output}' is invalid")

    # pylint: disable=broad-exception-caught
    except Exception as err:

        if getattr(args,"debug"):
            raise

        print(f"ERROR [loads]: {err}")
        return E_FAILED

if __name__ == "__main__":

    main("print","-S=CA","-C=Alameda")