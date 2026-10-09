import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    This notebook is used to validate the choice of holdout and harmonics on individual counties.
    """)
    return


@app.cell
def _(Counties):
    counties = Counties()
    states = counties["ST"].unique()
    counties = [f"{y} {x}" for x,y in counties[["ST","COUNTY"]].values]
    state_counties = {x:[" ".join(y.split()[:-1]) for y in counties if y.endswith(x)] for x in states}
    return state_counties, states


@app.cell
def _(mo, states):
    state_ui = mo.ui.dropdown(options=states,value="CA",label="State:")
    return (state_ui,)


@app.cell
def _(mo, state_counties, state_ui):
    _options = state_counties[state_ui.value]
    county_ui = mo.ui.dropdown(options=_options,value=_options[0],label="County:")
    return (county_ui,)


@app.cell
def _(mo):
    holdout_ui = mo.ui.array(
        [
            mo.ui.slider(start=3, stop=10,label="Holdout every",show_value=True,debounce=True,value=6),
            mo.ui.radio(options={"Days": "d", "Weeks": "w", "Months": "m"},inline=True,value="Days"),
        ]
    )
    return (holdout_ui,)


@app.cell
def _(county_ui, holdout_ui, mo, state_ui):
    mo.hstack([state_ui,county_ui,mo.hstack(holdout_ui,justify='end')],justify='start')
    return


@app.cell
def _(county_ui, state_ui):
    state = state_ui.value
    county = county_ui.value
    county_st = f"{county} {state}"
    return (county_st,)


@app.cell
def _(Estimator, EstimatorConfig, county_st, holdout_ui, mo):
    config = EstimatorConfig(holdout=f"{holdout_ui[0].value}{holdout_ui[1].value}")
    with mo.status.spinner("Running load estimator"):
        model = Estimator(county_st,config=config)
    status = model.reset_index().set_index(["status","timestamp"])
    model["holdout"] = float('nan')
    _prediction = status.loc["H"]
    model.loc[_prediction.index,"holdout"] = _prediction["prediction"]
    return config, model, status


@app.cell
def _(config, county_st, plt, status):
    # create scatter plot
    _fig = plt.figure(figsize=(10,6))
    _ax = _fig.gca()
    _ax = status.loc["T"].plot(x="actual",y="prediction",marker=".",linestyle="",markersize="1",ax=_ax)
    _ax = status.loc["H"].plot(x="actual",y="prediction",marker="x",linestyle="",markersize="1",ax=_ax)
    _min,_max = min(status.actual),max(status.actual)
    _ax = plt.plot([_min,_max],[_min,_max],"k",label="Perfect prediction")
    plt.legend(["Training",f"Holdout ({config.holdout})","Perfection"])
    plt.grid()
    plt.xlabel("Actual power (MW)")
    plt.ylabel("Predicted power (MW)")
    plt.title(county_st)
    scatter_plot = _fig
    plt.close()
    return (scatter_plot,)


@app.cell
def _(county_st, model, plt):
    # create time-series plot
    _fig = plt.figure(figsize=(10,6))
    _ax = _fig.gca()
    model.plot(y="actual",ax=_ax)
    model.plot(y="holdout",ax=_ax)
    plt.grid()
    plt.xlabel("Date/Time (UTC)")
    plt.ylabel("Power (MW)")
    plt.title(county_st)
    timeseries_plot = _fig
    plt.close()
    return (timeseries_plot,)


@app.cell
def _(county_st, model, plt):
    # create temperature plot
    _fig = plt.figure(figsize=(10,6))
    _ax = _fig.gca()
    plt.scatter(x=model["temperature_degF"],y=model["actual"],marker=".")
    plt.scatter(x=model["temperature_degF"],y=model["holdout"],marker=".")
    plt.grid()
    plt.xlabel(r"Temperature ($^\circ$F)")
    plt.ylabel("Power (MW)")
    plt.title(county_st)
    temperature_plot = _fig
    plt.close()
    return (temperature_plot,)


@app.cell
def _(county_st, model, plt):
    # create humidity plot
    _fig = plt.figure(figsize=(10,6))
    _ax = _fig.gca()
    plt.scatter(x=model["humidity_pc"],y=model["actual"],marker=".")
    plt.scatter(x=model["humidity_pc"],y=model["holdout"],marker=".")
    plt.grid()
    plt.xlabel(r"Relative Humidity (%)")
    plt.ylabel("Power (MW)")
    plt.title(county_st)
    humidity_plot = _fig
    plt.close()
    return (humidity_plot,)


@app.cell
def _(humidity_plot, mo, scatter_plot, temperature_plot, timeseries_plot):
    mo.ui.tabs({
        "Scatter": mo.mpl.interactive(scatter_plot),
        "Timeseries": mo.mpl.interactive(timeseries_plot),
        "Temperature": mo.mpl.interactive(temperature_plot),
        "Humidity": mo.mpl.interactive(humidity_plot),
    })
    return


@app.cell
def _():
    return


@app.cell
def _(config, get_mae, get_mape, get_r2, get_rmse, mo, model):
    _holdout = model[model.status=="H"][["actual","prediction"]]
    _peak = model.actual.max()
    _mean = model.actual.mean()
    _mae = get_mae(_holdout)
    _mape = get_mape(_holdout)
    _rmse = get_rmse(_holdout)
    _r2 = get_r2(_holdout)
    mo.md(f"""
    | Holdout | MAPE | MAE | RMSE | R$^2$ |
    | ------- | ---- | --- | ---- | ----- |
    | {config.holdout} | {_mape:.2f}% | {_mae:.2f} MW | {_rmse:.2f} MW | {_r2:.2f} |
    | % of mean: | | {_mae/_mean*100:.2f}% | {_rmse/_mean*100:.2f}%
    | % of peak: | | {_mae/_peak*100:.2f}% | {_rmse/_peak*100:.2f}%""")
    return


@app.cell
def _(np):
    def get_mae(df):
        """Calculate the mean absolute error"""
        return np.mean(np.abs(df.actual - df.prediction))

    def get_rmse(df):
        """Calculate the holdout root mean squared error"""
        return np.sqrt(np.mean((df.actual - df.prediction) ** 2))

    def get_mape(df):
        """Calculate mean absolute percent error"""
        return (
            np.mean(np.abs((df.prediction - df.actual) / (df.actual + 1e-6)))
            * 100
        )

    def get_r2(df):
        """Calculate r-squared"""
        ss_res = np.sum((df.actual - df.prediction) ** 2)
        ss_tot = np.sum((df.actual - np.mean(df.actual)) ** 2)
        return 1 - (ss_res / ss_tot)

    return get_mae, get_mape, get_r2, get_rmse


@app.cell
def _():
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np

    from fips.counties import Counties
    from loads.estimator import Estimator, EstimatorConfig

    return Counties, Estimator, EstimatorConfig, mo, np, plt


if __name__ == "__main__":
    app.run()
