import marimo

__generated_with = "0.20.2"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    This notebook evaluates the clusters to see what value of lag is ideal.
    """)
    return


@app.cell
def _(pd):
    clusters = pd.read_csv("clusters.csv")
    medoids = clusters.medoid.unique()
    configs = pd.read_csv("configs.csv",index_col=[0])
    return configs, medoids


@app.cell
def _(Total, configs, medoids, np, pd):
    date_range = pd.date_range(
        "2018-01-01 00:00:00+0000", "2018-12-31 23:59:59+0000", freq="1h"
    )

    # holdout dates per 3/4/25 Slack conversation
    n_weeks = 6
    holdout = (date_range.dayofyear // 7) % n_weeks == n_weeks - 1
    train = date_range[~holdout]
    test = date_range[holdout]

    # holdout test
    data = {}
    lags = list(range(7))
    for county_st in medoids:
        county = " ".join(county_st.split(" ")[:-1])
        state = county_st.split(" ")[-1]
        data[county_st] = {}
        _config = configs.loc[county_st]
        Total.TSGAM_CONFIG.multi_periodic_config.num_harmonics = _config[["nh_year","nh_week","nh_day"]].astype(int).values
        Total.TSGAM_CONFIG.exog_config[0].n_knots = int(_config.n_knots)
        Total.TSGAM_CONFIG.ar_config.lags = list(range(1,int(_config.lags_pm)+1))
        for lag in lags:
            Total.TSGAM_CONFIG.exog_config[0].lags = list(range(-lag, lag + 1, 1))
            print(f"{state=} {county=} {lag=}", end="... ", flush=True)
            print(Total.TSGAM_CONFIG)
            try:
                _result = Total.test(
                    state,
                    county,
                    n_samples=100,
                    holdout=holdout,
                ).copy()
                _samples = [x for x in _result.columns if x.startswith("sample_")]
                _result["median"] = np.percentile(_result[_samples], 50.0, axis=1)
                _result.drop(_samples, inplace=True, axis=1)
                _result.loc[train, _result.columns] = float("nan")
                data[county_st][lag] = _result
                print("OK")
            except Exception as err:
                print("ERROR:", err)
                raise
    return data, lags


@app.cell
def _(data, lags, mo, np):
    _output = [f"| County | {' | '.join(map(lambda x:f'{x}h lag',lags))} | Optimal |",f"| {' | '.join(['----' for _ in range(len(lags)+2)])} |"]
    for _county,_lags in ((x,data[x]) for x in sorted(data)):
        _rmse = []
        for _lag,_result in _lags.items():
            _rmse.append(np.sqrt(((_result["elec_total_MW"] - _result["median"] )**2).mean()))
        _min = _rmse.index(min(_rmse))
        _output.append(f"| {_county} | {' | '.join(('**' if n==_min else '') + f'{x/1e3:.2f}' + ('**' if n==_min else '') for n,x in enumerate(_rmse))} | {_min}h")
    mo.md("RMSE (GW)\n---------\n\n"+"\n".join(_output))
    return


@app.cell
def _():
    import marimo as mo
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from total import Total

    return Total, mo, np, pd


if __name__ == "__main__":
    app.run()
