# Totals

- [x] Read residential, commercial, industrial, and agricultural load data from NREL

- [x] Collect county-level totals

- [x] Aggregate counties total loads to geographic nodes such as WECC240 busses

- [x] Change training from {RES,COM}stock weather to NSRDB weather

- [ ] Read solar and wind DG from NREL (rooftop solar is compiled from NREL
  dGen nodal data in `loads.dgen`; wind is not done)

- [x] Calculate net loads

- [x] Calibrate net loads w.r.t. EIA energy use at state level and regional
  peaks (see `loads.calibrate`)

- [x] Produce 95th percentile samples from TSGAM (see `samples` and
  `percentile` in `loads.total.Total`)

# Clustering

- [x] Singular-value decomposition of county loads

- [x] k-means clustering of SVD U-matrix to 99% of power spectrum

- [x] Cluster review notebook (`_explore/explore_clusters_marimo.py`)

- [x] Generate `_explore/explore_clusters.csv` for all counties, all total
  fields, for k from 2 to 10

# TSGAM

- [x] Normalize dependent variable to max

- [x] Process TSGAM using `temperature_degF` and `humidity_pc` exogenous variables

- [x] Add Bennet's holdout algorithm

- [x] Find optimal models for medoid counties

- [x] Check optimal models for random counties to see if they match medoid county optimal models
