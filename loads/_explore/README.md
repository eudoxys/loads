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
