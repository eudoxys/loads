import marimo

__generated_with = "0.19.6"
app = marimo.App(width="full")


@app.cell
def _(mo):
    mo.md(r"""
    # Loads module

    This notebook allows you to review the results of the `loads` module.  For details on the module implementation, see https://www.eudoxys.com/loads.
    """)
    return


@app.cell
def _(Counties, mo):
    counties = Counties(use_index=["RO","ST","COUNTY"]).loc["WECC"]
    state_ui = mo.ui.dropdown(label="State:",options=counties.index.get_level_values(0).unique(),value=counties.index.get_level_values(0)[0])
    return counties, state_ui


@app.cell
def _(counties, mo, state_ui):
    _counties = counties.loc[state_ui.value].index
    county_ui = mo.ui.dropdown(label="County:",options=_counties)
    return (county_ui,)


@app.cell
def _(mo):
    year_ui = mo.ui.radio(label="Year:",options=[str(x) for x in range(2018,2023)],value="2020",inline=True)
    return (year_ui,)


@app.cell
def _(mo):
    get_month, set_month = mo.state(None)
    return get_month, set_month


@app.cell
def _(dt, get_month, mo, set_month):
    month_ui = mo.ui.dropdown(
        label="Month:",
        options={dt.date(2018, n + 1, 1).strftime("%B"): n + 1 for n in range(12)},
        value=get_month(),
        on_change=set_month,
    )
    return (month_ui,)


@app.cell
def _(mo, year_ui):
    sample_ui = mo.ui.checkbox(label="Sample",value=year_ui.value!="2018")
    return (sample_ui,)


@app.cell
def _(county_ui, mo, month_ui, sample_ui, state_ui, year_ui):
    mo.hstack([
        state_ui, 
        county_ui,
        year_ui,
        month_ui,
        sample_ui,
    ], justify="start")
    return


@app.cell
def _(county_ui, state_ui, year_ui):
    STATE = state_ui.value
    COUNTY = county_ui.value
    YEAR = year_ui.value
    return COUNTY, STATE, YEAR


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
    xaxis_ui = mo.ui.radio(
        label="X axis:",
        options=[x for x in data.reset_index().columns if not x.endswith("_MW")],
        inline=True,
        value=get_xaxis(),
        on_change=set_xaxis,
    )
    yaxis_ui = mo.ui.radio(
        label="Y axis:",
        options=sorted([x for x in data.columns if x.startswith("elec_")]),
        inline=True,
        value=get_yaxis(),
        on_change=set_yaxis,
    )
    zaxis_ui = mo.ui.radio(
        label="X axis:",
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
def _(COUNTY, STATE, data, plt):
    try:
        _piedata = {x:data[f"elec_{x}_MW"].sum() for x in ["residential","commercial","industrial","agricultural","transportation"]}
        _pie = plt.pie(
            x=[y for x,y in _piedata.items() if y > 0],
            labels=[f"{x} ({y/1000:.1f} GWh)" for x,y in _piedata.items() if y > 0],
        )
        plt.title(f"{COUNTY} {STATE} Total Energy Consumption")
        pieplot = plt.gca()
    except Exception as err:
        print(err)
        pieplot = None
    return (pieplot,)


@app.cell
def _(
    COUNTY,
    STATE,
    YEAR,
    data,
    get_plotter,
    get_xaxis,
    get_zaxis,
    mo,
    month_ui,
    pd,
    pieplot,
    plotter_options,
    plotter_ui,
    xaxis_ui,
    yaxis_ui,
    zaxis_ui,
):
    if month_ui.value is None:
        _data = data.round(1)
    else:
        _data = data.loc[
            pd.date_range(
                start=f"{YEAR}-{month_ui.value}-01 00:00:00+00:00",
                end=f"{YEAR}-{month_ui.value+1}-01 00:00:00+00:00",
                freq="1h",
            )
        ].round(1)
        _data.index.name = "timestamp"

    mo.ui.tabs(
        {
            "Plot": mo.vstack(
                [
                    mo.vstack([xaxis_ui, yaxis_ui, plotter_ui], justify="start"),
                    mo.ui.plotly(
                        plotter_options[get_plotter()](
                            _data.reset_index(),
                            x=get_xaxis(),
                            y=yaxis_ui.value,
                            title=f"{COUNTY} {STATE}",
                        )
                    ),
                ]
            ),
            "Weather": mo.vstack([zaxis_ui,mo.ui.plotly(
                plotter_options["line"](
                    _data.reset_index(),
                    x="timestamp",
                    y=get_zaxis(),
                    title=f"{COUNTY} {STATE}",
                )
            )]),
            "Data": mo.ui.table(
                data=_data[[x for x in data.columns if x.endswith("_MW")] + [x for x in data.columns if not x.endswith("_MW")]].round(4),
                selection=None,
                text_justify_columns={x: "right" for x in data.columns},
                page_size=24,
            ),
            "Pie": pieplot,
        }
    )
    return


@app.cell
def _(COUNTY, STATE, Total, YEAR, mo, sample_ui):
    mo.stop(
        COUNTY is None,
        mo.md("**<font color=blue>HINT**: you need to select a county</font>"),
    )

    with mo.status.spinner(f"Processing totals for {COUNTY} {STATE} in {YEAR}...") as _spinner:
        data = Total(STATE, COUNTY, YEAR,samples=None if YEAR==2018 else (1 if sample_ui.value else 0))
    return (data,)


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
    return Counties, Total, dt, mo, pd, plt, px


if __name__ == "__main__":
    app.run()
