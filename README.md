[![validate](https://github.com/eudoxys/loads/actions/workflows/validate.yaml/badge.svg)](https://github.com/eudoxys/loads/actions/workflows/validate.yaml)

Electric loads data accessor and multi-sector load data tool

# Documentation

See https://www.eudoxys.com/loads

# Installation

    pip install git+https://github.com/eudoxys/loads

# Examples

## Command line

Get the Alameda county California residential load data

    loads print -S=CA -C=Alameda

Outputs

                               elec_baseload_MW  elec_cooling_MW  elec_dg_MW  elec_heating_MW  elec_net_MW  elec_total_MW  nonelec_baseload_MW  nonelec_cooling_MW  nonelec_heating_MW  nonelec_total_MW
    timestamp                                                                                                                                                                                           
    2018-01-01 00:00:00+00:00        281.892669           1.7496     -1.0535           2.0579   284.646669     285.700069           509.669469              0.0049             34.3793        544.053669
    2018-01-01 01:00:00+00:00        289.359369           1.1131      0.0000           2.4693   292.941769     292.941769           513.807569              0.0034             40.0684        553.879369
    2018-01-01 02:00:00+00:00        295.018669           0.6803      0.0000           3.7304   299.429369     299.429369           515.856769              0.0029             49.9559        565.815669
    .
    .
    .
    2018-12-31 21:00:00+00:00        277.309369           1.8679     -6.3966           3.3568   276.137269     282.533969           507.140169              0.0143             44.8301        551.984469
    2018-12-31 22:00:00+00:00        275.588869           2.1452     -5.3423           2.8486   275.240469     280.582669           505.091169              0.0127             38.0819        543.185869
    2018-12-31 23:00:00+00:00        275.565069           2.5066     -3.7245           1.8676   276.214569     279.939069           505.597969              0.0099             30.8302        536.437969

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

# Caveat

- Although a data cache is used extensively to avoid multiple/slow queries, the
  processing of this large amount of data can be very time-consuming.

- Some COMstock and RESstock building types have no data in some counties. In
  such cases, a warning is output and a zero dataframe is constructed.
