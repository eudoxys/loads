Explore Modules
---------------

This file contains scripts and marimo notebooks used to explore the behavior
of modules in the loads package.

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

