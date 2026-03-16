# Totals

- [x] Read residential, commercial, industrial, and agricultural load data from NREL

- [x] Collect county-level totals

- [x] Aggregate counties total loads to geographic nodes such as WECC240 busses

- [ ] Read solar and wind DG from NREL

- [ ] Calculate net loads

- [ ] Calibrate `elec_total_MW` based on `elec_net_MW` w.r.t. EIA energy use at
  state level, stratefied as monthly DG level

- [ ] Produce 95th percentile samples from TSGAM

# Clustering

- [x] Singular-value decomposition of county loads

- [x] k-means clustering of SVD U-matrix to 99% of power spectrum

- [x] Cluster review notebook

- [x] Generate `tests/clusters.csv` for all counties, all total fields, for k from 2 to 10

# TSGAM

- [x] Normalize dependent variable to max

- [x] Process TSGAM using `temperature_degF` and `humidity_pc` exogenous variables

- [x] Add Bennet's holdout algorithm

- [x] Find optimal models for medoid counties

- [x] Check optimal models for random counties to see if the match medoid county optimal models
