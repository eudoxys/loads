# pylint: disable=line-too-long

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

    ['Riverside CA', 'Orange CA', 'Los Angeles CA', 'King WA', 'Salt Lake UT', 'Maricopa AZ']

The load clusters are evaluated by `tests.py` and `evaluate_lag.py` to find
the optimal TSGAM configuration, which is found to be as follows:

| County         | Year Harmonics | Week Harmonics | Day Harmonics | Knots | AR Lag (h) | Exogenous Window (h) | RMSE (GW) |
| -------------- | -------------- | -------------- | ------------- | ----- | ---------- | -------------------- | --------- |
| King WA        |       2        |        3       |      12       |   3   |    10      |         >6           |    0.13   |
| Los Angeles CA |       2        |        4       |      12       |   4   |     7      |          5           |    0.67   |
| Maricopa AZ    |       2        |        3       |      12       |   7   |     3      |          5           |    0.26   |
| Orange CA      |       4        |        4       |      12       |   5   |     6      |         >6           |    0.13   |
| Riverside CA   |       2        |        2       |      12       |   7   |    10      |          2           |    0.18   |
| Salt Lake UT   |       4        |        3       |      12       |   3   |     4      |          5           |    0.04   |

Each county's model is based on which county cluster medoid it is associated
with, as provided in `clusters.csv`.
"""

# pylint: enable=line-too-long

from typing import Callable

import pandas as pd
import numpy as np
import sklearn
import sklearn.cluster

from fips import Counties
from loads.total import Total

class Cluster:
    """County clustering class implementation"""

    # pylint: disable=too-many-instance-attributes
    RANDOM_STATE=0
    """Initial state of random number generator for kmeans clustering algorithm"""

    N_INIT="auto"
    """Value of KMeans `n_init` parameter"""

    cache = {}

    def __init__(self,
        # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        counties:list,
        column:str,
        threshold:float=0.99,
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

        If the `preprocess` function is callable, then the specified column
        data is passed to the specified function before SVD is performed.

        If `progress` is callable then callback is called for each county as
        it is processed. It is called with `None` when processing is done.

        Methodology
        -----------

        Each county's hourly data is first rolled by the county's standard
        time UTC offset (`fips.Counties` `TZOFFSET`) so that each day starts at
        local midnight. The hours rolled off one end of the year wrap around to
        the other end, consistent with the simulated load data.

        K-means clustering is performed using the left-most column of the $U$
        matrix returned by the singular value decomposition of each county's
        specified data column. The sign of each $U_0$ is chosen so its
        elements sum to a non-negative value, because the SVD sign is
        arbitrary. The `U` attribute contains the collected $U_0$ column
        vectors. The k-means clustering is weighted according to the county's
        total energy consumption, the value of which is available in the `W`
        attribute. The normalized singular values of each county are available
        in the `D` attribute, of which `D[n][0]` is the significance of $U_0$.
        The `K` attribute is the largest number of singular components needed
        by any county to reach `threshold` of its power spectrum. The mean
        county normalized load is available in the `M` attribute.

        Caveat
        ------

        The `loads.cluster.Cluster.__init__` constructor calls
        `loads.total.Total`, which can take considerable amount of time if
        the data flow has not been previously processed and cached.
        """

        if refresh:
            self.cache = {}

        # pylint: disable=invalid-name

        self.C = list(counties)
        """County names"""

        self.U = []
        """Collected $U_0$ column vectors from county data SVD"""

        self.D = []
        """Collected normalized $D$ values from county data SVD"""

        self.W = []
        """County energy weights"""

        self.L = []
        """County mean loadshape"""

        self.M = []
        """County mean-normalized mean loadshape"""

        self.Mnorm = []
        """County loadshape means"""

        self.P = []
        """County max-normalized mean loadshape"""

        self.Pnorm = []
        """County loadshape peaks"""

        self.K = 1
        """Largest number of singular components needed by any county to reach
        the power spectrum threshold"""

        # read county data
        self.loaddata(counties,column,threshold,preprocess,progress,refresh)

        # pylint: enable=invalid-name

        self.cluster = None
        """K-means clustering object (see `sklearn.cluster.KMeans`)"""

        self.centroids = None
        """K-means clustering centroid vectors"""

        self.closest = None
        """Index of the member county nearest each cluster centroid"""

        self.medoids = None
        """K-means clustering medoid county name (the member county nearest
        each cluster centroid)"""

        self.members = None
        """K-means clustering member county names"""

        if progress:
            progress(None)

    def loaddata(self,counties,column,threshold,preprocess,progress,refresh):
        # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        """Read county data for the specified column"""
        tzoffsets = self._tzoffsets()
        for county in counties:

            # load data
            if progress:
                progress(county)
            state_abbr = county.split(" ")[-1]
            county_name = " ".join(county.split(" ")[:-1])
            if county in self.cache and not refresh:
                data = self.cache[county]
            else:
                data = Total(state_abbr,county_name).fillna(0)
                self.cache[county] = data
            data = data[column]
            start = data.index[0] if isinstance(data.index,pd.DatetimeIndex) else None
            if preprocess:
                data = preprocess(data)
            values = np.asarray(data)
            if len(values) % 24 != 0:
                raise ValueError(f"{county} {column} data has {len(values)} rows, which is not a whole number of days")

            # roll data so each day starts at local (standard time) midnight
            values = np.roll(values,-self._midnight(start,tzoffsets[county]))
            load = np.reshape(values,(-1,24)).T

            u,d,_ = np.linalg.svd(load)

            # evaluate power spectrum
            dsum = np.sum(d)
            if dsum > 0:
                self.D.append(d/dsum)
                # number of components needed to reach the threshold
                k = int(np.searchsorted(np.cumsum(self.D[-1]),threshold)) + 1
                k = min(k,len(d))
            else:
                self.D.append(np.array([1.0]+[0.0]*(len(d)-1)))
                k = 1

            # get U_0 with a deterministic sign
            self.K = max(self.K,k)
            u0 = u[:,0]
            self.U.append(-u0 if np.sum(u0) < 0 else u0)

            # get mean load and normalize mean loadshape
            m = np.mean(load,axis=1)
            self.L.append(m)
            mm = np.mean(m)
            self.M.append(m / mm if mm != 0 else np.zeros_like(m))
            self.Mnorm.append(mm)

            # get peak load and normalize peak loadshape
            p = np.max(load,axis=1)
            pp = np.max(load)
            self.P.append(p / pp if pp != 0 else np.zeros_like(p))
            self.Pnorm.append(pp)

            # save county weight
            self.W.append(float(load.sum()/1e6))

        self.U = np.array(self.U)

    _TZOFFSETS = {}

    @classmethod
    def _tzoffsets(cls) -> dict:
        """@private Get standard time UTC offsets (hours) of counties keyed by `County ST`"""
        if not cls._TZOFFSETS:
            cls._TZOFFSETS = {f"{y} {x}":int(z)
                for x,y,z in Counties()[["ST","COUNTY","TZOFFSET"]].values}
        return cls._TZOFFSETS

    @staticmethod
    def _midnight(start:pd.Timestamp|None,tzoffset:int) -> int:
        """@private Get the index of the first sample at local standard time midnight

        Arguments
        ---------

          - `start`: timestamp of the first sample (UTC is assumed if `None`
            or tz-naive)

          - `tzoffset`: standard time UTC offset in hours (e.g., -8 for PST)

        Returns
        -------

          - `int`: sample index in the range [0,23]
        """
        if start is None:
            hour = 0
        elif start.tzinfo is None:
            hour = start.hour
        else:
            hour = start.tz_convert("UTC").hour
        return (-hour-tzoffset) % 24

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

          - `loads.cluster.Cluster.closest`: the index of the member county
            nearest each cluster centroid

          - `loads.cluster.Cluster.medoids`: the cluster medoid names, i.e.,
            the member county nearest each cluster centroid

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

        # find the member of each cluster nearest its centroid
        self.closest = []
        for n,centroid in enumerate(self.cluster.cluster_centers_):
            index = np.flatnonzero(self.cluster.labels_ == n)
            distance = np.linalg.norm(self.U[index] - centroid,axis=1)
            self.closest.append(int(index[np.argmin(distance)]))
        self.closest = np.array(self.closest)
        self.medoids = [self.C[x] for x in self.closest]
        self.members = [[self.C[m] for m,x in enumerate(self.cluster.labels_) if x == n]
            for n in range(n_clusters)]

        return self.cluster

if __name__ == '__main__':

    # pylint: disable=pointless-string-statement

    """
    This test script generates tests/clusters.csv of all WECC counties for k
    in [2..10]
    """

    counties_list = [f"{y} {x}" for x,y in Counties(use_index="RO", selection="WECC")[
        ["ST", "COUNTY"]
        ].values]

    result = []
    MAX_K = 10
    columns = list(Total.COLUMNS.keys())
    print("Reading county data",end="...",flush=True)
    for _column in columns:

        cluster = Cluster(counties_list,column=_column,preprocess=np.abs)
        for _k in range(2,MAX_K+1):

            cluster.kmeans(n_clusters=_k)
            for medoid,members in zip(cluster.medoids,cluster.members):
                _states = [x.split(" ")[-1] for x in members]
                _counties = [" ".join(x.split(" ")[:-1]) for x in members]
                df = pd.DataFrame({"state":_states,"county":_counties})
                df["column"] = _column
                df["k"] = _k
                df["medoid"] = medoid
                result.append(df)
        print(_column,"ok")
    pd.concat(result)\
        .sort_values(["state","county","column","k"])\
        .to_csv("tests/clusters.csv",index=False,header=True)
