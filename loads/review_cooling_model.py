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
def _(Cast, Residential, Weather, county_ui, mo, os, pd, state_ui):
    mo.stop(county_ui.value is None,mo.md("**<font color=blue>HINT**: select a county</font>"))
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
    # data.reset_index(inplace=True)

    order_ui = mo.ui.slider(label="Model order:",start=1,stop=72,step=1,value=3,debounce=True,show_value=True)
    order_ui
    return COUNTY, LOAD, STATE, data, order_ui


@app.cell
def _(COUNTY, LOAD, STATE, data, np, plt):
    plt.clf()

    X = data["temperature_degF"].values
    Y = data[f"elec_{LOAD}_MW"].values
    t = data.index.values

    # data.set_index("timestamp",inplace=True)
    model = data.static_model(weather=data,return_model=True)["cooling"]
    # data.reset_index(inplace=True)

    Xr = np.arange(min(X),max(X)+1,1)
    Ym = model(Xr)

    plt.figure(figsize=(12,5))
    plt.plot(X, Y, ".b",label="Load data")
    plt.plot(Xr, Ym, "k",label="Baseline model")

    plt.xlabel("Temperature ($^\\text{o}$F)")
    plt.title(f"{COUNTY} {STATE} {LOAD}")
    plt.ylabel("Load (MW)")
    plt.grid()
    plt.legend()

    plt.gca()
    return X, Y, model


@app.cell
def _(X, Y, model):
    Yf = model(X)
    Yr = Y - Yf
    return Yf, Yr


@app.cell
def _(Y, Yr, np, order_ui):
    K=order_ui.value
    YY=np.vstack([Y[k:len(Yr)-K+k+1] for k in range(K)])
    return K, YY


@app.cell
def _(K, X, YY, Yf, np):
    # raise Exception("YY columns are backwards")
    M = np.concat([[Yf[K-1:]],
                   YY[-2::-1,],
                   np.array([X[K-1:]]),
                  ]).T
    b = np.array([YY[-1]]).T
    return M, b


@app.cell
def _(M):
    # check the transfer function matrix M
    print("  Pm[t]    P[t-1]    P[t-2]     T[t]")
    print("--------  --------  --------  --------")
    print("\n".join([', '.join([f'{y:8.4f}' for y in x]) for x in M[:10,:].tolist()]))
    return


@app.cell
def _(K, M, Y, b, mo, np):
    x = np.linalg.lstsq(M,b)[0]
    Yd = (M@x + b)/2
    _y = np.array([Y[K-1:]]).T
    _rmse = np.sqrt(np.mean((_y-Yd)**2))
    mo.md(f"""
    | Model fit | $~$ |
    | :------ | :----- |
    | Dynamic model | $P[t] = {'~'.join([(f'{y:+.4f}~P[{{t{-K+n:.0f}}}]' if n > 0 else f"{y:.4f}~\\bar P[t]") if n<K else f"{y:+.4f}~T[t]" for n,y in enumerate(x.T.tolist()[0])])}$ |
    | Model RMSE | ${_rmse:.3f}$ MW (${_rmse/np.mean(_y)*100:.1f}$%) |
    """)
    return (Yd,)


@app.cell
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
def _(K, Yd, data, mo, pd, plotter_ui, xaxis_ui, yaxis_ui):
    if yaxis_ui.value == "elec_cooling_MW":
        _data = pd.DataFrame(
            {
                xaxis_ui.value: data.reset_index()[xaxis_ui.value][K - 1 :],
                f"Actual {yaxis_ui.value}": data.reset_index()[yaxis_ui.value][K - 1 :],
                f"Model {yaxis_ui.value}": Yd.T.tolist()[0],
            }
        )
        fig = mo.ui.plotly(
            plotter_ui.value(
                _data,
                x=xaxis_ui.value,
                y=[f"Actual {yaxis_ui.value}",f"Model {yaxis_ui.value}"],
            )
        )
    else:
        fig = mo.ui.plotly(
            plotter_ui.value(
                data.reset_index(), x=xaxis_ui.value, y=yaxis_ui.value
            )
        )
    mo.ui.tabs({
        "Plots":fig,
        "Data": mo.ui.table(
            data=data.round(4),
            selection=None,
            text_justify_columns={x:"right" for x in data.columns},
            page_size=24,
        ),
    })
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
    return Cast, Counties, Residential, Weather, mo, np, os, pd, plt, px


if __name__ == "__main__":
    app.run()
