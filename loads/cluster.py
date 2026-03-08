"""County clustering

Example
-------

The following example performs k-means clustering of WECC counties into 6
clusters based on total electric load:

    from fips import Counties
    counties = [f"{y} {x}" for x,y in Counties(use_index="RO", selection="WECC")[["ST", "COUNTY"]].values]
    from loads import Cluster
    cluster = Cluster(counties,"elec_total_MW")
    cluster.kmeans(n_clusters=6)
    print(cluster.medoids)

The output is

    {'Kings CA', 'Maricopa AZ', 'Pierce WA', 'Los Angeles CA', 'Lewis and Clark MT', 'Apache AZ'}

"""

from typing import Callable

import pandas as pd
import numpy as np
import sklearn

from loads.total import Total

class Cluster:
    """County clustering class implementation"""

    RANDOM_STATE=0
    """Initial state of random number generator for kmeans clustering algorithm"""

    N_INIT="auto"
    """Value of KMeans `n_init` parameter"""

    cache = {}

    def __init__(self,
        counties:list,
        column:str,
        threshold:int=0.99,
        preprocess:Callable=None,
        progress:Callable=None,
        refresh:bool=False,
        ):
        """Construct county clustering object

        Arguments
        ---------

          - `counties`: list of counties to process

          - `column`: data column to use when processing

          - `threshold`: power spectrum threshold value

          - `preprocess`: data preprocessing function

          - `progress`: progress callback

          - `refresh`: refresh internal data cache

        Description
        -----------

        The `counties` members must be provided in the format `NAME ST` where
        `NAME` is the canonical county name(i.e., without "County", "Parish",
        etc.) and `ST` is state abbreviation (e.g., "AZ")

        The `column` value must be the name of a column included in the `Total`
        data.

        If the `preprocessing` function is callable, then the specified column
        data is passed to the specified function before SVD is performed.

        If `progress` is callable then callback is called for each county as
        it is processed. It is called with `None` when processing is done.

        Methodology
        -----------

        K-means clustering is performed using the left-most column of the $U$
        matrix returned by the singular value decomposition of each county's
        specified data column. The `U` attribute contains the collected $U_0$
        column vectors. The k-means clustering is weighted according to the
        county's total energy consumption, the value of which is available in
        the `W` attribute. The significance of the $U_0$ of each county is
        available in the `D` attribute.  The mean county normalized load is
        available in the `M` attribute.

        Caveat
        ------

        The `loads.cluster.Cluster.__init__` constructor calls
        `loads.total.Total`, which can take considerable amount of time if
        the data flow has not been previously processed and cached.
        """

        if refresh:
            self.cache = {}

        self.C = list(counties) # list of counties
        """County names"""

        self.U = [] # u[:,0] matrix from SVD of column
        """Collected $U_0$ column vectors from county data SVD"""

        self.D = [] # normalized power spectrum of cluster
        """Collected normalized $D$ values from county data SVD"""
        
        self.W = [] # county weights
        """County energy weights"""

        self.M = [] # county mean normalized loadshape
        """County normalized mean loads"""

        self.K = 1 # power spectrum threshold value (columns of U)
        """Power spectrum threshold value"""

        for county in counties:
            if progress:
                progress(county)
            state_abbr = county.split(" ")[-1]
            county_name = " ".join(county.split(" ")[:-1])
            if county in self.cache:
                data = self.cache[county]
            else:
                data = Total(state_abbr,county_name).fillna(0)
                self.cache[county] = data
            data = data[column]
            if preprocess:
                data = preprocess(data)
            load = np.reshape(data.values,(365,24)).T
            u,d,_ = np.linalg.svd(load)
            dsum = np.sum(d)
            if dsum > 0:
                self.D.append(d/dsum)
                spectrum = [x for x in np.cumsum(self.D[-1]) if x<threshold]
                k = len(spectrum) if spectrum else None
            else:
                self.D.append(np.array([1.0]+[0.0]*(len(d)-1)))
                k = 1
            self.K = max(self.K,len(self.D[-1]) if k is None else k)
            # self.U.append(u[:,0:k].flatten())
            self.U.append(u)
            m = np.mean(load,axis=1)
            mm = np.mean(m)
            self.M.append(m / mm if mm != 0 else 0.0)
            self.W.append(float(load.sum()/1e6))

        self.U = np.array([x[:,0:self.K].flatten() for x in self.U])

        self.cluster = None
        """K-means clustering object (see `numpy.linalg.kmeans`)"""
        
        self.centroids = None
        """K-means clustering centroid vectors"""

        self.closest = None
        """K-means clustering closest cluster"""

        self.medoids = None
        """K-means clustering medoid county name"""

        self.members = None
        """K-means clustering member county names"""

        if progress:
            progress(None)

    def kmeans(self,
        n_clusters:int,
        ) -> sklearn.cluster.KMeans:
        """Perform clustering analysis on county data

        Arguments
        ---------

          - `n_clusters`: desired number of clusters

        Returns
        -------

          - `sklearn.cluster.KMeans`: k-means cluster fit

        Description
        -----------

        Performs the k-means cluster for the given number of clusters.
        Sets the follow attributes:

          - `loads.cluster.Cluster.cluster`: the k-means cluster object

          - `loads.cluster.Cluster.centroids`: the cluster centroid vectors

          - `loads.cluster.Cluster.medoids`: the cluster medoid names

          - `loads.cluster.Cluster.members`: the cluster member names
        """
        assert isinstance(n_clusters,int), "n_clusters must be an integer"
        assert n_clusters > 1, "n_clusters must be greater than 1"

        self.cluster = sklearn.cluster.KMeans(
            n_clusters=n_clusters,
            n_init=self.N_INIT,
            random_state=self.RANDOM_STATE,
            )
        try:
            self.cluster.fit(self.U,sample_weight=self.W)
        except Exception as err:
            print("EXCEPTION:",err)
            print(self.U)
            raise
        
        self.centroids = self.cluster.cluster_centers_.tolist()
        self.closest, _ = sklearn.metrics.pairwise_distances_argmin_min(self.cluster.cluster_centers_, self.U)
        self.medoids = [self.C[x] for x in self.closest]
        self.members = [[self.C[m] for m,x in enumerate(self.cluster.labels_) if x == n] 
            for n in range(n_clusters)]

        return self.cluster

if __name__ == '__main__':
    
    from fips import Counties
    counties = [f"{y} {x}" for x,y in Counties(use_index="RO", selection="WECC")[
        ["ST", "COUNTY"]
        ].values]

    for column,check in {
        "elec_total_MW": {
            'Lewis and Clark MT',
            'Los Angeles CA',
            'Kings CA',
            'Apache AZ',
            'Pierce WA',
            'Maricopa AZ',
            },
        "elec_dg_MW": {
            'Riverside CA',
            'Douglas OR',
            'Contra Costa CA',
            'Jefferson CO',
            'Maricopa AZ',
            'Alameda CA',
            }
        }.items():
        print("Testing",column,end="",flush=True)
        cluster = Cluster(counties,
            column=column,
            preprocess=np.abs,
            progress=lambda x:print(end=".",flush=True) if x else print(flush=True),
            )
        cluster.kmeans(n_clusters=len(check))
        # assert cluster.medoids == check, f"{column} medoids is not correct: {cluster.medoids=} != {check=}"
        print(column,cluster.medoids)

