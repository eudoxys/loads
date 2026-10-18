Explore Modules
---------------

This file contains scripts and marimo notebooks used to explore the behavior
of modules in the loads package.

## Clusters

The `explore_clusters_marimo.py` notebook is used to chose a cluster
configuration that will be used by the other modules in the `loads` package
that use cluster medoids, e.g., `loads.estimator`. Generally clustering is
should be used whenever processing all counties is cost-prohibitive. However
care should be taken to ensure that the clustering variable used is suitable
for the problem being solved. The `loads.estimator` for example needs the
`elec_total_MW` variable by default, but another can be chosen using this
notebook if desired.

## Estimator

The `explore_estimator.py` script runs the estimator on the cluster medoid
counties for a range of harmonics that are likely to include the harmonics
that minimize errors. Four error metrics are collected, including MAE, RMSE,
MAPE, and R$^2$. Speed is also collected. These are stored in
`explore_estimator.csv`.

The results stored in `esplore_estimator_cluster.csv` are the best values obtain
by a search the most parsimonious harmonics that are within 1% of the best harmonics obtained from the sweep search.

The marimo notebook `explore_estimator_marimo.py` is used to visualize the
results of the exploration script.

## WECC estimate

The marimo notebook `explore_wecc_estimate_marimo.py` displays the hourly
county loads in `loads/wecc/wecc_estimate.csv.gz` for a selected state and
county. Run `loads/wecc/wecc_estimate.py` first to generate that file.

## Calibration

The marimo notebook `explore_calibrate_marimo.py` explores the sensitivity of
the August 2020 WECC calibration (`loads.calibrate.Calibrate`) to its
objective weights. It shows the trade-off between load-shape deformation,
state-energy error, and peak attainment across the predeclared 88-point
weight grid, marks the candidate chosen by the selection rule, and re-solves
a chosen point to report its active constraints and duals, a first-order
probe of the peak ceilings, the regional profiles, and the counties that
carry the adjustment. It uses the inputs of `loads/_test/test_calibrate.py`;
run `python loads/_test/test_calibrate.py` first to build the cached load
matrix. A saved weight sweep is reused when available; otherwise the notebook
runs the search on request.
