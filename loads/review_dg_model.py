import marimo

__generated_with = "0.18.4"
app = marimo.App(width="full")


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
    mo.hstack([state_ui, county_ui], justify="start")
    return


@app.cell
def _(mo):
    get_northeast,set_northeast = mo.state(True)
    get_east,set_east = mo.state(True)
    get_southeast,set_southeast = mo.state(True)
    get_south,set_south = mo.state(True)
    get_southwest,set_southwest = mo.state(True)
    get_west,set_west = mo.state(True)
    get_northwest,set_northwest = mo.state(True)
    get_altitude,set_altitude = mo.state(True)

    def set_all(status):
        set_northeast(status)
        set_east(status)
        set_southeast(status)
        set_south(status)
        set_southwest(status)
        set_west(status)
        set_northwest(status)
        set_altitude(status)
    return (
        get_altitude,
        get_east,
        get_northeast,
        get_northwest,
        get_south,
        get_southeast,
        get_southwest,
        get_west,
        set_all,
        set_altitude,
        set_east,
        set_northeast,
        set_northwest,
        set_south,
        set_southeast,
        set_southwest,
        set_west,
    )


@app.cell
def _(mo):
    global_ui = mo.ui.checkbox(label="Horizontal",value=True)
    diffuse_ui = mo.ui.checkbox(label="Diffuse",value=True)
    direct_ui = mo.ui.checkbox(label="Direct",value=False)
    return diffuse_ui, direct_ui, global_ui


@app.cell
def _(
    get_east,
    get_northeast,
    get_northwest,
    get_south,
    get_southeast,
    get_southwest,
    get_west,
    mo,
    set_east,
    set_northeast,
    set_northwest,
    set_south,
    set_southeast,
    set_southwest,
    set_west,
):
    northeast_ui = mo.ui.checkbox(label="Northeast",value=get_northeast(),on_change=set_northeast)
    east_ui = mo.ui.checkbox(label="East",value=get_east(),on_change=set_east)
    southeast_ui = mo.ui.checkbox(label="Southeast",value=get_southeast(),on_change=set_southeast)
    south_ui = mo.ui.checkbox(label="South",value=get_south(),on_change=set_south)
    southwest_ui = mo.ui.checkbox(label="Southwest",value=get_southwest(),on_change=set_southwest)
    west_ui = mo.ui.checkbox(label="West",value=get_west(),on_change=set_west)
    northwest_ui = mo.ui.checkbox(label="Northwest",value=get_northwest(),on_change=set_northwest)
    return (
        east_ui,
        northeast_ui,
        northwest_ui,
        south_ui,
        southeast_ui,
        southwest_ui,
        west_ui,
    )


@app.cell
def _(get_altitude, mo, set_all, set_altitude):
    all_ui = mo.ui.button(label="All",on_click=lambda x: set_all(True))
    none_ui = mo.ui.button(label="None",on_click=lambda x: set_all(False))
    altitude_ui = mo.ui.checkbox(label="with altitude",value=get_altitude(),on_change=set_altitude)
    return all_ui, altitude_ui, none_ui


@app.cell
def _(mo):
    # constraint_ui = mo.ui.radio(
    #     label="Constraint:",
    #     options={"None": 0, "Non-negative normals": 1, "Non-negative generation": 2},
    #     inline=True,
    #     value="None",
    # )
    constrain_normals = mo.ui.checkbox(label="Non-negative normals",value=True)
    constrain_generation = mo.ui.checkbox(label="Non-negative generation",value=True)
    constraints_ui = mo.hstack([mo.md("Constraints:"),constrain_normals,constrain_generation],justify="start")
    return constrain_generation, constrain_normals, constraints_ui


@app.cell
def _(
    Counties,
    all_ui,
    altitude_ui,
    constraints_ui,
    county_ui,
    diffuse_ui,
    direct_ui,
    east_ui,
    global_ui,
    mo,
    none_ui,
    northeast_ui,
    northwest_ui,
    south_ui,
    southeast_ui,
    southwest_ui,
    state_ui,
    west_ui,
):
    STATE = state_ui.value
    COUNTY = county_ui.value
    mo.stop(
        COUNTY is None, mo.md("**<font color=blue>HINT**: select a county</font>")
    )
    _county = Counties(use_index=["ST", "COUNTY"]).loc[STATE, COUNTY]
    tzoffset = _county.TZOFFSET.values[0]
    latitude = _county.LAT.values[0]

    mo.vstack(
        [
            mo.hstack(
                [mo.md("Irradiances:"), global_ui, diffuse_ui, direct_ui],
                justify="start",
            ),
            mo.hstack(
                [
                    mo.md("Normals:"),
                    northeast_ui,
                    east_ui,
                    southeast_ui,
                    south_ui,
                    southwest_ui,
                    west_ui,
                    northwest_ui,
                    all_ui,
                    none_ui,
                    altitude_ui,
                ],
                justify="start",
            ),
            constraints_ui,
        ]
    )
    return COUNTY, STATE, latitude, tzoffset


@app.cell
def _(COUNTY, Cast, Residential, STATE, Weather, mo, os, pd, tzoffset):
    LOAD = "cooling"
    tzoffset
    with mo.status.spinner(f"Loading {COUNTY} {STATE} data..."):
        cache = os.path.join(".cache", f"{STATE}_{COUNTY}_R.csv")
        if os.path.exists(cache):
            _test = pd.read_csv(cache, index_col=0, parse_dates=[0])
        else:
            _test = Residential(state=STATE, county=COUNTY)
            _test.to_csv(cache)

    data = Cast(_test,2025,Weather(STATE,COUNTY))
    data.index.name="timestamp"
    return (data,)


@app.cell
def _(
    data,
    diffuse_ui,
    direct_ui,
    get_altitude,
    get_east,
    get_northeast,
    get_northwest,
    get_south,
    get_southeast,
    get_southwest,
    get_west,
    global_ui,
    latitude,
    np,
    tzoffset,
):
    basecolumns = (
        (["global"] if global_ui.value else [])
        + (["diffuse"] if diffuse_ui.value else [])
        + (["direct"] if direct_ui.value else [])
    )
    M = data[[f"{x}_Wpms" for x in basecolumns]].copy()
    M.index = M.index.tz_convert(int(tzoffset) * 3600)
    M.columns = basecolumns
    t = data.index.hour / 12 * np.pi
    columns = basecolumns.copy()
    if get_altitude():
        _declination = -23.44*np.pi/180 * np.cos((data.index.dayofyear-1+10+data.index.hour/24)/365.2425*2*np.pi) 
        _altitude = np.cos(np.asin(np.sin(latitude) * np.sin(_declination) + np.cos(latitude)*np.cos(_declination)*np.cos((data.index.hour-12)/12*np.pi)))
    else:
        _altitude = 1.0
    for direction, active, angle in [
        ("northeast", get_northeast(), 3 * np.pi / 4),
        ("east", get_east(), np.pi),
        ("southeast", get_southeast(), 5 * np.pi / 4),
        ("south", get_south(), 3 * np.pi / 2),
        ("southwest", get_southwest(), 7 * np.pi / 4),
        ("west", get_west(), 0),
        ("northwest", get_northwest(), np.pi / 4),
    ]:
        if active:
            M[direction] = data["direct_Wpms"] * np.clip(
                np.cos(t - angle)*_altitude, a_min=0, a_max=1
            )
            columns.append(f"{direction}")
    M = M.values
    b = -data[["elec_dg_MW"]].values
    return M, b, basecolumns, columns


@app.cell
def _(M, b, basecolumns, constrain_generation, constrain_normals, cp, np):
    x = cp.Variable(M.shape[1])
    cost = cp.sum_squares(M@x-b.T)
    constraints = [] + ([x[len(basecolumns):]>=0] if constrain_normals.value and M.shape[1]>len(basecolumns) else []) + ([M@x>=0] if constrain_generation.value else [])
    prob = cp.Problem(cp.Minimize(cost),constraints)
    prob.solve(solver="CLARABEL")
    fit = np.array([x.value]).T if not x.value is None else None
    def model(M=M):
        return np.array([np.clip(M@x.value,a_min=0,a_max=None)]).T
    return fit, model, prob


@app.cell
def _(columns, fit, mo):
    if fit is None:
        _result = mo.md("No solution")
    else:
        _result = mo.md("<BR>".join([f"$\\beta_{n} = {x[0] if abs(x[0])>1e-6 else 0.0:+.4f} \\quad$ ({columns[n]})" for n,x in enumerate(fit)]))
    _result
    return


@app.cell
def _(b, fit, mo, model, np):
    if fit is None:
        _result = None
    else:
        _rmse = np.sqrt(np.mean((model()-b)**2))
        _mean = np.mean(b)
        _result = mo.md(f"Solar model RMSE: {_rmse:.2f} MW ({_rmse/_mean*100:.1f}%)")
    _result
    return


@app.cell
def _(mo):
    plot_ui = mo.ui.radio(options=["Scatter","Time-series"],value="Scatter",inline=True)
    return (plot_ui,)


@app.cell
def _(M, b, columns, data, fit, mo, model, pd, plot_ui, prob, px, tzoffset):
    if not fit is None:
        _data = pd.DataFrame(b,columns=["Data (MW)"])
        _data["Model (MW)"] = model()
        match plot_ui.value:
            case "Scatter":
                _graph = px.scatter(_data, x="Data (MW)", y="Model (MW)")
                _graph.add_scatter(
                    x=[0, max(b)], y=[0, max(b)], mode="lines", showlegend=False
                )
            case "Time-series":
                _data.index.name = "Date/Time"
                _graph = px.line(_data)
        _plot = mo.ui.plotly(_graph)
    else:
        _plot = mo.md(f"No solution ({prob.value=})")


    _data = (
        data["elec_dg_MW"].to_frame().abs().round(1).rename({"elec_dg_MW": "data"},axis=1)
    )
    _solar = pd.DataFrame(M, columns=columns, index=data.index).round(1)
    if not fit is None:
        _data["model"] = model().round(1)
    _frame = pd.concat([_data, _solar], axis=1).iloc[-int(tzoffset) :]
    _frame.index = _frame.index.tz_convert(int(tzoffset*3600))
    _table = mo.ui.table(
        _frame,
        page_size=24,
        selection=None,
        text_justify_columns={x: "right" for x in _frame.columns},
    )

    mo.ui.tabs(
        {
            "Plot": mo.vstack([plot_ui, _plot]),
            "Data": _table,
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
    from fips.counties import Counties, County
    from loads.residential import Residential
    Residential.CACHEDIR=".cache"
    from loads.weather import Weather
    from loads.cast import Cast
    import cvxpy as cp
    return Cast, Counties, Residential, Weather, cp, mo, np, os, pd, px


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
