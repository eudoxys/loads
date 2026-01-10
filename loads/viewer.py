import marimo

__generated_with = "0.19.1"
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
    residential_ui = mo.ui.checkbox(label="Residential",value=True)
    commercial_ui = mo.ui.checkbox(label="Commercial",value=True)
    industrial_ui = mo.ui.checkbox(label="Industrial",value=True)
    agricultural_ui = mo.ui.checkbox(label="Agricultural",value=True)
    year_ui = mo.ui.radio(label="Year:",options=[str(x) for x in range(2018,2023)],value="2020",inline=True)
    return (
        agricultural_ui,
        commercial_ui,
        industrial_ui,
        residential_ui,
        year_ui,
    )


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
def _(county_ui, mo, month_ui, state_ui, year_ui):
    mo.hstack([
        state_ui, 
        county_ui,
        year_ui,
        month_ui,
    ], justify="start")
    return


@app.cell
def _(agricultural_ui, commercial_ui, industrial_ui, mo, residential_ui):
    mo.hstack([mo.md("Loads:"),residential_ui,commercial_ui,industrial_ui,agricultural_ui],justify='start')
    return


@app.cell
def _(
    Agriculture,
    Cast,
    Commercial,
    Industry,
    Residential,
    Weather,
    agricultural_ui,
    commercial_ui,
    county_ui,
    industrial_ui,
    mo,
    os,
    pd,
    residential_ui,
    state_ui,
    year_ui,
):
    STATE = state_ui.value
    COUNTY = county_ui.value

    mo.stop(
        COUNTY is None,
        mo.md("**<font color=blue>HINT**: you need to select a county</font)"),
    )

    pd.options.display.max_columns = None
    pd.options.display.width = None

    cache = os.path.join(".cache", f"{STATE}_{COUNTY}_R.csv")
    data = Weather(STATE, COUNTY)
    for field in ["baseload", "heating", "cooling", "dg", "total", "net"]:
        data[f"elec_{field}_MW"] = data[f"nonelec_{field}_MW"] = 0.0
    loadshape = pd.DataFrame(
        data=[1.0] * 8760,
        index=pd.date_range(
            start="2018-01-01 00:00:00+00:00",
            end="2018-12-31 23:59:59+00:00",
            freq="1h",
        ),
    )
    datasets = {
        "Residential": Residential(STATE, COUNTY),
        "Commercial": Commercial(STATE, COUNTY),
        "Industry": Industry(STATE, COUNTY, loadshape),
        "Agriculture": Agriculture(STATE, COUNTY, loadshape),
    }
    for column in datasets["Residential"].columns:
        for dataset in ["Industry", "Agriculture"]:
            if column not in datasets[dataset]:
                datasets[dataset][column] = 0.0
    for ui, dataset in [
        (residential_ui, "Residential"),
        (commercial_ui, "Commercial"),
        (industrial_ui, "Industry"),
        (agricultural_ui, "Agriculture"),
    ]:
        if ui.value:
            _data = datasets[dataset]
            for field in _data.columns:
                data[field] += _data[field]
    source = data.copy()
    year = int(year_ui.value)
    timestamps = pd.date_range(
        start=f"{year}-01-01 00:00:00+00:00",
        end=f"{year}-12-31 23:59:59+00:00",
        freq="1h",
    )
    weather = Weather(STATE, COUNTY)
    weather.index = timestamps[: len(weather)]
    if len(timestamps) > len(weather):
        weather = pd.concat(
            [weather, weather.iloc[: len(timestamps) - len(weather)]], axis=0
        )
        weather.index = timestamps
    data = Cast(data, year, weather)
    data.index.name = "timestamp"
    return COUNTY, STATE, data, datasets, year


@app.cell
def _(mo):
    get_xaxis, set_xaxis = mo.state("timestamp")
    get_yaxis, set_yaxis = mo.state("elec_net_MW")
    get_plotter, set_plotter = mo.state("line")
    return get_plotter, get_xaxis, get_yaxis, set_plotter, set_xaxis, set_yaxis


@app.cell
def _(
    data,
    get_plotter,
    get_xaxis,
    get_yaxis,
    mo,
    px,
    set_plotter,
    set_xaxis,
    set_yaxis,
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
        options=[x for x in data.columns if x.startswith("elec_")],
        inline=True,
        value=get_yaxis(),
        on_change=set_yaxis,
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
    mo.vstack([xaxis_ui, yaxis_ui, plotter_ui], justify="start")
    return plotter_options, xaxis_ui, yaxis_ui


@app.cell
def _(COUNTY, STATE, datasets, plt, yaxis_ui):
    _piedata = {x:datasets[x][yaxis_ui.value].sum() for x in datasets}
    _pie = plt.pie(
        x=[y for x,y in _piedata.items() if y > 0],
        labels=[f"{x} ({y/1000:.1f} GWh)" for x,y in _piedata.items() if y > 0],
    )
    plt.title(f"{COUNTY} {STATE} {yaxis_ui.value.replace('_',' ').title()}")
    pieplot = plt.gca()
    return (pieplot,)


@app.cell
def _(
    COUNTY,
    STATE,
    data,
    get_plotter,
    mo,
    month_ui,
    pd,
    pieplot,
    plotter_options,
    xaxis_ui,
    yaxis_ui,
    year,
):
    if month_ui.value is None:
        _data = data.round(1)
    else:
        _data = data.loc[
            pd.date_range(
                start=f"{year}-{month_ui.value}-01 00:00:00+00:00",
                end=f"{year}-{month_ui.value+1}-01 00:00:00+00:00",
                freq="1h",
            )
        ].round(1)
        _data.index.name = "timestamp"

    mo.ui.tabs(
        {
            "Plot": mo.ui.plotly(
                plotter_options[get_plotter()](
                    _data.reset_index(),
                    x=xaxis_ui.value,
                    y=yaxis_ui.value,
                    title=f"{COUNTY} {STATE}",
                )
            ),
            "Data": mo.ui.table(
                data=_data.round(4),
                selection=None,
                text_justify_columns={x: "right" for x in data.columns},
                page_size=24,
            ),
            "Pie": pieplot,
        }
    )
    return


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
        from loads import Residential, Commercial, Industry, Agriculture, Cast
        from weather import Weather
    return (
        Agriculture,
        Cast,
        Commercial,
        Counties,
        Industry,
        Residential,
        Weather,
        dt,
        mo,
        os,
        pd,
        plt,
        px,
    )


if __name__ == "__main__":
    app.run()
