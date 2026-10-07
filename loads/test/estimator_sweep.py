"""Perform sweep tests of estimator on key WECC counties"""

import pandas as pd

for county in pd.read_csv("../clusters.csv").medoid.unique():
	print(counties)