import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


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
def _(county_ui, mo, state_ui):
    mo.hstack([state_ui,county_ui],justify='start')
    return


@app.cell
def _(county_ui, state_ui):
    state = state_ui.value
    county = county_ui.value
    county_st = f"{county} {state}"
    return (county_st,)


@app.cell
def _(Estimator, county_st, mo):
    with mo.status.spinner("Running load estimator"):
        model = Estimator(county_st)
    status = model.reset_index().set_index(["status","timestamp"])
    model["holdout"] = float('nan')
    _prediction = status.loc["H"]
    model.loc[_prediction.index,"holdout"] = _prediction["prediction"]
    return model, status


@app.cell
def _(county_st, plt, status):
    # create scatter plot
    _fig = plt.figure(figsize=(10,6))
    _ax = _fig.gca()
    _ax = status.loc["T"].plot(x="actual",y="prediction",marker=".",linestyle="",markersize="1",ax=_ax)
    _ax = status.loc["H"].plot(x="actual",y="prediction",marker="x",linestyle="",markersize="1",ax=_ax)
    _min,_max = min(status.actual),max(status.actual)
    _ax = plt.plot([_min,_max],[_min,_max],"k",label="Perfect prediction")
    plt.legend(["Training","Holdout","Perfection"])
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
    import marimo as mo
    import matplotlib.pyplot as plt

    from fips.counties import Counties
    from loads.estimator import Estimator

    return Counties, Estimator, mo, plt


if __name__ == "__main__":
    app.run()
