"""WECC240 node load calibrated to EIA-930

This [marimo](https://marimo.io/) notebook reviews the WECC240 node loads
obtained by calibrating the WECC county net load estimate to the EIA-930
demand of the US WECC balancing authorities (BAs) with
`loads.calibrate.CalibrateForm930` and allocating the counties to the nodes
with `CalibrateForm930.allocate`, as in `eudoxys/wecc240` pull request #2.
Unlike `wecc240`, the net load is not clipped at zero: only the county gross
load is calibrated and the rooftop PV is fixed, so a node's net load is
negative where its PV exceeds its load.
The inputs are those of `loads/_validate/validate_calibrate_form930.py`.

Select a year and, optionally, a month to reduce the time window (the
calibration runs on the selected window only); "All" uses 2018–2022. Node
names come from the `wecc240` bus data.
"""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="WECC240 Calibrated Node Load")


@app.cell
def _(mo):
    mo.md(f"""
    ## {__doc__}
    """)
    return


@app.cell
def _(importlib, mo, pathlib):
    # load the calibration inputs (shared with the validation script)
    _file = pathlib.Path(*pathlib.Path(__file__).parts[:-2],"_validate","validate_calibrate_form930.py")
    _spec = importlib.util.spec_from_file_location("validate_calibrate_form930",_file)
    validation = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(validation)
    with mo.status.spinner("Loading county estimate, BA factors and EIA-930 demand"):
        load,dg,factors,demand,node_factors = validation.inputs()
    return demand, dg, factors, load, node_factors


@app.cell
def _(mo, pathlib, pd):
    # node names from the wecc240 bus data
    _local = pathlib.Path(*pathlib.Path(__file__).parts[:-3]).parent / "wecc240" / "wecc240" / "data"
    _url = "https://raw.githubusercontent.com/eudoxys/wecc240/main/wecc240/data"
    _name = _local / "bus_gis.csv" if _local.exists() else f"{_url}/bus_gis.csv"
    try:
        names = pd.read_csv(_name).groupby("GEOHASH")["NAME"].first().to_dict()
    except Exception: # pylint: disable=broad-exception-caught
        names = {}
    mo.md("")
    return (names,)


@app.cell
def _(load, mo):
    # time window selection
    year_ui = mo.ui.dropdown(options=["All"]+sorted({str(x) for x in load.index.year}),
        value="All",label="Year:")
    month_ui = mo.ui.dropdown(options=["All"]+[f"{x:02d}" for x in range(1,13)],
        value="All",label="Month:")
    mo.hstack([year_ui,month_ui],justify="start")
    return month_ui, year_ui


@app.cell
def _(load, month_ui, year_ui):
    # selected window
    if year_ui.value == "All":
        window = load.index
        period = "2018–2022"
    elif month_ui.value == "All":
        window = load.index[load.index.year == int(year_ui.value)]
        period = year_ui.value
    else:
        window = load.index[(load.index.year == int(year_ui.value))
            & (load.index.month == int(month_ui.value))]
        period = f"{year_ui.value}-{month_ui.value}"
    return period, window


@app.cell
def _(CalibrateForm930, demand, dg, factors, load, mo, node_factors, window):
    # calibrate the window and allocate to nodes
    with mo.status.spinner("Calibrating counties and allocating to nodes"):
        county = CalibrateForm930(load.loc[window],factors,demand.loc[window],dg=dg.loc[window])
        data = county.allocate(node_factors)
    return county, data


@app.cell
def _(county, data, mo, period):
    # summary
    _total = data.sum(axis=1,min_count=1)
    _complete = county.demand.notna().all(axis=1)
    _eia = county.demand.sum(axis=1)[_complete].sum()/1e6
    _uncal = county.estimate[county.uncalibrated].sum(axis=1)[_complete].sum()/1e6
    _node = _total[_complete].sum()/1e6
    mo.vstack([
        mo.hstack([
            mo.stat(f"{data.shape[1]}",label="Nodes",caption=f"{county.shape[1]} counties"),
            mo.stat(f"{len(county.demand.columns)}",label="BAs with demand",
                caption="uncalibrated: " + (", ".join(county.uncalibrated) or "none")),
            mo.stat(f"{_node:,.1f} TWh",label=f"Node energy ({period})",
                caption=f"EIA-930 {_eia:,.1f} TWh + uncalibrated {_uncal:,.2f} TWh"),
            mo.stat(f"{_total.max()/1e3:,.1f} GW",label="Node total peak",
                caption=f"{_total.idxmax():%Y-%m-%d %H:%M} UTC"),
            mo.stat(f"{int((~_complete).sum())}",label="Hours missing demand",
                caption="NaN for the nodes of the missing BAs"),
        ],justify="start"),
        mo.md(f"**Data:** {data.index[0]} to {data.index[-1]}, {len(data)} hours,"
            f" NaN values {int(data.isna().sum().sum())}, negative net node-hours {int((data<0).sum().sum())}"
            f" in {int((data<0).any().sum())} nodes,"
            f" max |node total − (EIA-930 + uncalibrated)| "
            f"{(_total - county.demand.sum(axis=1) - county.estimate[county.uncalibrated].sum(axis=1))[_complete].abs().max():.2g} MW"),
    ])
    return


@app.cell
def _(data, names, node_factors, pd):
    # node table
    node_table = pd.DataFrame({
        "name":pd.Series(names).reindex(data.columns),
        "counties":node_factors.groupby("node").county_st.apply(", ".join).reindex(data.columns),
        "energy_MWh":data.sum().round(0),
        "mean_MW":data.mean().round(1),
        "peak_MW":data.max().round(1),
        "peak_time":data.idxmax(),
        "min_MW":data.min().round(1),
        "negative_hours":(data < 0).sum(),
        "nan_hours":data.isna().sum(),
        }).rename_axis("node").sort_values("mean_MW",ascending=False).reset_index()
    return (node_table,)


@app.cell
def _(data, mo, names, period, plt):
    # node plot and group views (public names, so lazy tabs can call them
    # after this cell has run; marimo deletes a cell's private `_` names)
    def node_plot(node):
        """Plot one node's load over the window"""
        plt.close()
        ax = data[node].plot(figsize=(10,5),grid=True,linewidth=0.7 if len(data) > 744 else 1.0,
            xlabel="Date/Time (UTC)",ylabel="Power (MW)",
            title=f"{names.get(node,node)} ({node}), {period}")
        return ax.figure

    def node_group(nodes):
        """Plot and data tabs for a group of nodes"""
        return mo.ui.tabs({
            "Plot":mo.ui.tabs({f"{names.get(z,z)} ({z})":mo.lazy(lambda z=z:node_plot(z))
                for z in nodes},lazy=True),
            "Data":mo.ui.table(data[nodes].round(1),selection=None,page_size=24),
            },lazy=True)
    return (node_group,)


@app.cell
def _(data, mo, node_group, node_table):
    # node table and node groups, a few nodes per tab
    _nodes = sorted(data.columns)
    _step = 7
    _groups = {f"{_nodes[x]} $-$ {_nodes[min(x+_step,len(_nodes))-1]}":_nodes[x:x+_step]
        for x in range(0,len(_nodes),_step)}
    mo.ui.tabs({
        "Nodes":mo.ui.table(node_table,page_size=25,selection=None),
        **{x:mo.lazy(lambda y=y:node_group(y)) for x,y in _groups.items()},
        },lazy=True)
    return


@app.cell
def _():
    import marimo as mo
    import importlib.util
    import pathlib
    import pandas as pd
    import matplotlib.pyplot as plt
    from loads.calibrate import CalibrateForm930

    return CalibrateForm930, importlib, mo, pathlib, pd, plt


if __name__ == "__main__":
    app.run()
