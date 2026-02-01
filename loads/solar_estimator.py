"""Solar DG estimator

The distributed generation prediction uses a clipped least-squares fit. Samples
are generated using the mean error and standard deviation of the prediction
on the training data.
"""

import numpy as np
import spcqe

class SolarEstimatorConfig:
    """Solar estimator configuration data
    """

class SolarEstimator:
    """Solar estimator
    """

    def __init__(self,config=SolarEstimatorConfig,**kwargs):
        """Construct solar estimator
        """
        self.config = config
        self.model = None

    def __str__(self):
        return f"""Estimator:
    model={self.model.T.round(6).tolist()[0]}
    rmse={self.rmse.round(6)}
    rank={self.rank}
    sv={self.sv.round(2)}
    mbe={self.mbe.round(6)}
    std={self.std.round(6)}
"""

    def fit(self,
        X:np.array,
        y:np.array,
        ):
        """Fit solar DG estimator

        Arguments
        ---------

          - `X`: independent variables

          - `y`: dependent variables
        """
        X = np.array(X)
        y = np.array(y)
        result = np.linalg.lstsq(X,y)
        self.model = result[0]
        self.rmse = np.sqrt(result[1] / len(y))
        self.rank = result[2]
        self.sv = result[3]
        residuals = self.predict(X) - y
        self.mbe = np.mean(residuals)
        self.std = np.std(residuals)

    def predict(self,
        X:np.array):
        """Predict solar DG

        Arguments
        ---------

          - `X`: independent variables

        Returns
        -------

          - `np.array`: dependent variable prediction
        """
        Y = X @ self.model
        return np.clip(Y,a_min=0,a_max=None)

    def sample(self,
        X:np.array,
        n_samples:int=1,
        random_state:int=None,
        ):
        """Sample solar DG

        Arguments
        ---------

          - `X`: independent variables

          - `n_samples`: number of samples to draw

          - `random_state`: random number generator initial state

        Returns
        -------

          - `np.array`: dependent variable samples
        """
        if not random_state is None:
            np.random.seed(random_state)
        Y = self.predict(X)
        R = np.random.normal(self.mbe,self.std,size=(len(X),n_samples))
        R[np.where(Y==0)] = 0.0
        return np.clip(Y + R,a_min=0,a_max=None)

if __name__ == '__main__':
    
    """Process predictions and samples for all WECC states and counties

    Usage
    -----

        python3 solar_estimator.py [--plots]

    Options
    -------

      - `plots`: plots counties with peak DG above 10 MW
    """
    
    import sys
    import pandas as pd
    import matplotlib.pyplot as plt

    plots = "--plots" in sys.argv

    pd.options.display.width = None
    pd.options.display.max_columns = None

    from fips import Counties
    from loads.residential import Residential
    from loads.commercial import Commercial
    from weather import Weather

    total = 0
    for state,county in Counties(use_index="SYSTEM",selection="WECC")[["ST","COUNTY"]].values:

        X = Weather(state,county)

        data = []
        for sector,dataset in [
            ("residential",Residential),
            ("commercial",Commercial),
            ]:
            data.append(dataset(state,county).elec_dg_MW.to_frame())
        y = -sum(data)
        train = y.index[:8000]
        holdout = y.index[8000:]

        if y.loc[holdout].values.sum() > 0:
            estimator = SolarEstimator()
            estimator.fit(X.loc[train].values,y.loc[train].values)

            predict = estimator.predict(X.loc[holdout].values)

            peak = predict.max()
            total += peak
            rmse = np.sqrt(np.linalg.norm(y.loc[holdout].values-predict,2)/len(holdout))
            mpe = rmse/np.mean(y.loc[holdout].values)*100

            print(f"{county+' '+state:20s}: {peak=:5.1f} MW, {rmse=:4.1f} MW ({mpe:.1f}%)",flush=True)

            if plots and peak > 10:

                plt.figure(figsize=(16,8))

                Y = y.loc[holdout]
                pmax = max(Y.elec_dg_MW.max(),predict.max())
                
                plt.subplot(1,2,1)
                plt.plot(Y,"k",label="Holdout")
                plt.plot(Y.index,predict,".b",label="Prediction")
                plt.grid()
                plt.legend()
                plt.subplot(1,2,2)

                plt.plot(Y.elec_dg_MW,predict,".")
                plt.plot([0,pmax],[0,pmax],':k')
                plt.grid()

                plt.suptitle(f"{county} {state} {holdout[len(holdout)//2].strftime("%B %Y")}")
                plt.show()

        else:

            print(f"{county+' '+state:20s}: -",flush=True)

    print(f"{total=:.1f} MW")  
