import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium")


@app.cell
def _(Counties, mo):
    # state dropdown
    state_ui = mo.ui.dropdown(options=sorted(Counties(use_index="RO").loc["WECC"].ST.unique()))
    return (state_ui,)


@app.cell
def _(Counties, mo, state_ui):
    # county dropdown
    _options = sorted(Counties(use_index="ST").loc[state_ui.value].COUNTY) if state_ui.value else []
    county_ui = mo.ui.dropdown(options=_options)
    return (county_ui,)


@app.cell
def _(Residential, county_ui, mo, state_ui):
    # channel dropdown
    if state_ui.value and county_ui.value:
        dataset = Residential(state_ui.value,county_ui.value)
        _channels = sorted([x for x in dataset.columns if x.endswith("_MW")])
        _training = len(dataset)
    else:
        _channels = []
        _training = 8760
    channel_ui = mo.ui.dropdown(label="Channel:",options=_channels)
    holdout_ui = mo.ui.range_slider(label="Holdout window:",start=0,stop=_training,step=100,value=(8000,_training),debounce=True,show_value=True)
    return channel_ui, holdout_ui


@app.cell
def _(channel_ui, county_ui, holdout_ui, mo, state_ui):
    mo.hstack([state_ui,county_ui,channel_ui,holdout_ui],justify='start')
    return


@app.cell
def _(
    Residential,
    Weather,
    channel_ui,
    county_ui,
    estimate,
    holdout_ui,
    mo,
    np,
    os,
    pd,
    state_ui,
    ts,
):
    mo.stop(state_ui.value is None, mo.md("HINT: choose a state"))
    mo.stop(county_ui.value is None, mo.md("HINT: choose a county"))
    mo.stop(channel_ui.value is None, mo.md("HINT: choose a channel"))

    state = state_ui.value
    county = county_ui.value
    channel = channel_ui.value
    percentile = None  # percentile to draw from samples
    samples = 100  # number of samples to draw when percentile is not None

    # load data file
    os.makedirs("tsgam_test", exist_ok=True)
    file = f"tsgam_test/{state}_{county}_{channel}.csv"
    if os.path.exists(file):
        data = pd.read_csv(
            file, index_col=["timestamp"], parse_dates=["timestamp"]
        )
    else:
        data = Residential(state, county).join(Weather(state, county))[
            [channel, "temperature_degF"]
        ]
        for year in range(2019, 2023):
            data = pd.concat(
                [data, Weather(state, county, year)["temperature_degF"]]
            )
        data.columns = ["training", "temperature"]
        data.training = data.training.abs()
        data.to_csv(file, index=True, header=True)

    # prepare y (log-transformed load) and X (temperature only)
    holdout = data.iloc[holdout_ui.value[0] : holdout_ui.value[1]].dropna().index
    training = data.drop(holdout).dropna()
    training = training[training.training!=0].index
    y = np.log(data.loc[training].training.values)
    X = data.loc[training].temperature.to_frame()

    # multi-harmonic configuration for time features
    multi_harmonic_config = ts.TsgamMultiHarmonicConfig(
        num_harmonics=[6, 4, 3], periods=[365.2425 * 24, 7 * 24, 24]
    )

    # spline configuration for temperature (exogenous variable)
    exog_config: list[ts.TsgamSplineConfig | ts.TsgamLinearConfig] = [
        ts.TsgamSplineConfig(
            knots=[],  # Empty list means knots will be auto-generated from data
            n_knots=10,  # Number of knots to generate
            lags=[-3, -2, -1, 0, 1, 2, 3],
            reg_weight=1e-4,  # Regularization weight for coefficients
            diff_reg_weight=1.0,  # Regularization weight for differences between lags
        )
    ]

    # 36-hour AR model in baseline
    ar_config = ts.TsgamArConfig(lags=list(range(1, 36)))

    # solver configuration
    solver_config = ts.TsgamSolverConfig(solver="CLARABEL", verbose=False)

    # create main config
    config = ts.TsgamEstimatorConfig(
        multi_harmonic_config=multi_harmonic_config,
        exog_config=exog_config,
        ar_config=ar_config,
        solver_config=solver_config,
        random_state=None,
        debug=False,
    )

    # create estimator
    estimator = ts.TsgamEstimator(config=config)

    # perform fit
    estimator.fit(X, y)
    if not estimator.problem_.status in ["optimal", "optimal_inaccurate"]:
        raise RuntimeError(f"unable to fit: {estimate.problem_.status}")

    # predict and sample
    data["predict"] = np.exp(estimator.predict(data["temperature"].to_frame()))
    if percentile is None:
        data["sample"] = np.exp(estimator.sample(data["temperature"].to_frame()))[
            0
        ]
    else:
        data["sample"] = np.percentile(
            np.exp(estimator.sample(data["temperature"].to_frame(), samples)),
            percentile,
            axis=0,
        )
    return channel, county, data, holdout, state


@app.cell
def _(data, holdout, mo, np):
    # test holdout
    test = data.loc[holdout]
    predict_rmse = np.sqrt(
        np.sum((test["predict"] - test["training"]) ** 2) / len(test)
    )
    sample_rmse = np.sqrt(
        np.sum((test["sample"] - test["training"]) ** 2) / len(test)
    )
    mo.md(f"""
    Predict RMSE: {predict_rmse:.1f} MW ({predict_rmse/test["training"].mean()*100:.1f}%)
    <br/>
    Sample RMSE: {sample_rmse:.1f} MW ({sample_rmse/test["training"].mean()*100:.1f}%)
    """)
    return


@app.cell
def _(channel, county, data, mo, state):
    # plot
    import plotly.express as px
    _plot = px.line(
        data.reset_index(),
        x="timestamp",
        y=["training","predict","sample"],
        labels={
            "timestamp": "Date/Time",
        },
        title=f"{county} {state} {channel}"
    )
    mo.ui.plotly(_plot,config={"scrollZoom":True})
    return


@app.cell
def _():
    import marimo as mo
    import os
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from fips import Counties
    from loads import Residential, Commercial
    from weather import Weather
    import tsgam_estimator as ts
    return Counties, Residential, Weather, mo, np, os, pd, ts


if __name__ == "__main__":
    app.run()
