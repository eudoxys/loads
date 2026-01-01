import marimo

__generated_with = "0.18.4"
app = marimo.App(width="full")


@app.cell
def _(mo):
    mo.md(r"""
    # Cooling model

    This notebook allow you to review the results and performance of the cooling load model.  For details on the model implementation, see https://www.eudoxys.com/loads/loads/cast.html.
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
def _(county_ui, mo, state_ui):
    model_ui = mo.ui.radio(
        label="Data:",
        options=["Cooling", "Heating", "Baseload", "DG", "Total", "Net"],
        value="Cooling",
        inline=True,
    )
    mo.hstack([state_ui, county_ui,model_ui], justify="start")
    return


@app.cell
def _(county_ui, mo):
    mo.stop(county_ui.value is None,mo.md("**<font color=blue>HINT**: select a county</font>"))
    order_ui = mo.ui.slider(label="Model order:",start=1,stop=24,step=1,value=1,debounce=True,show_value=True)
    # order_ui
    return (order_ui,)


@app.cell
def _(Cast, Residential, Weather, county_ui, mo, order_ui, os, pd, state_ui):
    order_ui
    STATE = state_ui.value
    COUNTY = county_ui.value
    LOAD = "cooling"

    pd.options.display.max_columns = None
    pd.options.display.width = None

    with mo.status.spinner(f"Loading {COUNTY} {STATE} data..."):
        cache = os.path.join(".cache", f"{STATE}_{COUNTY}_R.csv")
        if os.path.exists(cache):
            _test = pd.read_csv(cache, index_col=0, parse_dates=[0])
        else:
            _test = Residential(state=STATE, county=COUNTY)
            _test.to_csv(cache)

    data = Cast(_test,2025,Weather(STATE,COUNTY))
    data.index.name="timestamp"
    return LOAD, data


@app.cell
def _(LOAD, data, order_ui):
    # fit the model
    X = data["temperature_degF"].values
    Y = data[f"elec_{LOAD}_MW"].values
    t = data.index.values

    # baseline model (sigmoid fit)
    baseline_model = data.static_model()["cooling"]
    Yf = baseline_model(X) # baseline model fit

    # dynamic model (linear fit to residual)
    K = order_ui.value
    dynamic_model = data.dynamic_model(order=K)["cooling"]
    Yd = dynamic_model(X)
    return K, Y, Yd, Yf


@app.cell
def _(K, Y, Yd, mo, np):
    _rmse = np.sqrt(np.mean((Y[K-1:]-Yd)**2))
    mo.md(f"""RMSE = ${_rmse:.3f}$ MW (${_rmse/np.mean(Y)*100:.1f}$%)""")
    return


@app.cell(hide_code=True)
def _(data, mo, px):
    xaxis_ui = mo.ui.radio(
        label="X axis:",
        options=[x for x in data.reset_index().columns if not x.endswith("_MW")],
        inline=True,
        value="timestamp"
    )
    yaxis_ui = mo.ui.radio(
        label="Y axis:",
        options=[x for x in data.columns if x.startswith("elec_")],
        inline=True,
        value="elec_cooling_MW"
    )
    plotter_ui = mo.ui.radio(label="Plotter:",options={"line":px.line,"scatter":px.scatter},value="line",inline=True)
    mo.vstack([xaxis_ui, yaxis_ui,plotter_ui], justify="start")
    return plotter_ui, xaxis_ui, yaxis_ui


@app.cell
def _(K, Y, Yd, Yf, data, mo, pd, plotter_ui, xaxis_ui, yaxis_ui):
    if yaxis_ui.value == "elec_cooling_MW":
        _data = pd.DataFrame(
            {
                xaxis_ui.value: data.reset_index()[xaxis_ui.value].iloc[K - 1 :],
                f"Original {yaxis_ui.value}": Y[K - 1 :],
                f"Prediction {yaxis_ui.value}": Yd,
                f"Baseline {yaxis_ui.value}": Yf[K - 1 :],
            }
        )
        fig = mo.ui.plotly(
            plotter_ui.value(
                _data,
                x=xaxis_ui.value,
                y=[f"Original {yaxis_ui.value}", f"Prediction {yaxis_ui.value}", f"Baseline {yaxis_ui.value}"],
            )
        )
    else:
        fig = mo.ui.plotly(
            plotter_ui.value(
                data.reset_index(), x=xaxis_ui.value, y=yaxis_ui.value
            )
        )
    mo.ui.tabs(
        {
            "Plots": fig,
            "Data": mo.ui.table(
                data=data.round(4),
                selection=None,
                text_justify_columns={x: "right" for x in data.columns},
                page_size=24,
            ),
        }
    )
    return


@app.cell
def _():
    import os
    import marimo as mo
    import pandas as pd
    import numpy as np
    import matplotlib.pyplot as plt
    import plotly.express as px
    import plotly.graph_objects as go
    from scipy.optimize import curve_fit
    from fips.counties import Counties
    from loads.residential import Residential
    Residential.CACHEDIR=".cache"
    from loads.weather import Weather
    from loads.cast import Cast
    return Cast, Counties, Residential, Weather, mo, np, os, pd, px


if __name__ == "__main__":
    app.run()
