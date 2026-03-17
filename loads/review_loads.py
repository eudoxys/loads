import marimo

__generated_with = "0.20.2"
app = marimo.App(width="full")


@app.cell
def _(mo):
    mo.md(r"""
    # Loads module

    This notebook allows you to review the results of the `loads` module.  For details on the module implementation, see https://www.eudoxys.com/loads.
    """)
    return


@app.cell
def _(county_ui, date_ui, mo, samples_ui, state_ui, training_ui):
    mo.hstack([
        state_ui, 
        county_ui,
        date_ui,
        training_ui,
        samples_ui
    ], justify="start")
    return


@app.cell
def _(data_ui, mo, pie_ui, plot_ui, weather_ui):
    mo.ui.tabs(
        {
            "Power": plot_ui,
            "Energy": pie_ui,
            "Weather": weather_ui,
            "Data": data_ui,
        }
    )
    return


@app.cell
def _(Counties, mo):
    # state selection
    counties = Counties(use_index=["RO","ST","COUNTY"]).loc["WECC"]
    state_ui = mo.ui.dropdown(label="State:",options=counties.index.get_level_values(0).unique(),value=counties.index.get_level_values(0)[0])
    return counties, state_ui


@app.cell
def _(counties, mo, state_ui):
    # county selection
    _counties = counties.loc[state_ui.value].index
    county_ui = mo.ui.dropdown(label="County:",options=_counties)
    return (county_ui,)


@app.cell
def _(mo):
    # date range selection
    date_ui = mo.ui.date_range(label="Date range:",value=("2018-01-01","2018-12-31"))
    return (date_ui,)


@app.cell
def _(mo):
    # sampling selection
    training_ui = mo.ui.checkbox(label="Training")
    return (training_ui,)


@app.cell
def _(mo, training_ui):
    # sample count selection
    samples_ui = mo.ui.slider(label="Samples:",steps=[0,1,100,1000,10000],value=100,disabled=training_ui.value==True,debounce=True,show_value=True)
    return (samples_ui,)


@app.cell
def _(mo):
    get_xaxis, set_xaxis = mo.state("timestamp")
    get_yaxis, set_yaxis = mo.state("elec_total_MW")
    get_zaxis, set_zaxis = mo.state("temperature_degF")
    return get_xaxis, get_yaxis, get_zaxis, set_xaxis, set_yaxis, set_zaxis


@app.cell
def _(get_xaxis, mo):
    get_plotter, set_plotter = mo.state("line" if get_xaxis()=="timestamp" else "scatter")
    return get_plotter, set_plotter


@app.cell
def _(
    data,
    get_plotter,
    get_xaxis,
    get_yaxis,
    get_zaxis,
    mo,
    px,
    set_plotter,
    set_xaxis,
    set_yaxis,
    set_zaxis,
):
    xaxis_ui = mo.ui.dropdown(
        label="X axis:",
        options=[x for x in data.reset_index().columns if not x.endswith("_MW")],
        # inline=True,
        value=get_xaxis(),
        on_change=set_xaxis,
    )
    yaxis_ui = mo.ui.dropdown(
        label="Y axis:",
        options=sorted([x for x in data.columns if x.startswith("elec_")]),
        # inline=True,
        value=get_yaxis(),
        on_change=set_yaxis,
    )
    zaxis_ui = mo.ui.radio(
        label="Y axis:",
        options=[x for x in data.reset_index().columns if not x.endswith("_MW") and x != "timestamp"],
        inline=True,
        value=get_zaxis(),
        on_change=set_zaxis,
    )
    plotter_options = {
        "line": px.line, 
        "scatter": px.scatter, 
        # "area": px.area,
    }
    plotter_ui = mo.ui.radio(
        label="Plotter:",
        options=plotter_options.keys(),
        value=get_plotter(),
        on_change=set_plotter,
        inline=True,
    )
    return plotter_options, plotter_ui, xaxis_ui, yaxis_ui, zaxis_ui


@app.cell
def _(Total, county_ui, date_ui, mo, pd, samples_ui, state_ui, training_ui):
    mo.stop(
        county_ui.value is None,
        mo.md(
            "**<font color=blue>HINT**: you need to select a county_ui.value</font>"
        ),
    )

    with mo.status.spinner(
        f"Processing totals for {county_ui.value} {state_ui.value}..."
    ) as _spinner:
        data = Total(
            state_ui.value,
            county_ui.value,
            samples=None if training_ui.value else samples_ui.value,
            date_range=pd.date_range(*date_ui.value,freq="1h")[:-1],
            refresh=True,
        ).round(3)
    return (data,)


@app.cell
def _(county_ui, data, plt, state_ui):
    _piedata = {x:data[f"elec_{x}_MW"].sum() for x in ["residential","commercial","industrial","agricultural","transportation"]}
    _pie = plt.pie(
        x=[y for x,y in _piedata.items() if y > 0],
        labels=[f"{x.title()} ({y/1000:.1f} GWh)" for x,y in _piedata.items() if y > 0],
        autopct="%.0f%%"
    )
    plt.title(f"{county_ui.value} {state_ui.value} Total Energy Consumption")
    pie_ui = plt.gca()
    return (pie_ui,)


@app.cell
def _(
    county_ui,
    data,
    get_plotter,
    get_xaxis,
    mo,
    plotter_options,
    plotter_ui,
    state_ui,
    xaxis_ui,
    yaxis_ui,
):
    plot_ui = mo.vstack(
                [
                    mo.hstack([xaxis_ui, yaxis_ui, plotter_ui], justify="start"),
                    mo.ui.plotly(
                        plotter_options[get_plotter()](
                            data.reset_index(),
                            x=get_xaxis(),
                            y=yaxis_ui.value,
                            title=f"{county_ui.value} {state_ui.value}",
                        )
                    ),
                ]
            )
    return (plot_ui,)


@app.cell
def _(county_ui, data, get_zaxis, mo, plotter_options, state_ui, zaxis_ui):
    weather_ui = mo.vstack([zaxis_ui,mo.ui.plotly(
                plotter_options["line"](
                    data.reset_index(),
                    x="timestamp",
                    y=get_zaxis(),
                    title=f"{county_ui.value} {state_ui.value}",
                )
            )])
    return (weather_ui,)


@app.cell
def _(data, mo):
    data_ui = mo.ui.table(
                data=data[[x for x in data.columns if x.endswith("_MW")] + [x for x in data.columns if not x.endswith("_MW")]].round(4),
                selection=None,
                text_justify_columns={x: "right" for x in data.columns},
                page_size=24,
            )
    return (data_ui,)


@app.cell
def _():
    import marimo as mo
    with mo.status.spinner("Loading modules...") as spinner:
        import os
        import datetime as dt
        import pandas as pd
        import numpy as np
        import matplotlib.pyplot as plt
        import plotly.express as px
        import plotly.graph_objects as go
        from scipy.optimize import curve_fit
        from fips import Counties
        from loads import Total
        from weather import Weather
    return Counties, Total, mo, pd, plt, px


if __name__ == "__main__":
    app.run()
