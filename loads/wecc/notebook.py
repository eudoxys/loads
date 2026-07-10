import marimo

__generated_with = "0.23.6"
app = marimo.App(width="medium")


@app.cell
def _(mo):
    mo.md(r"""
    County-level solar DG retrodiction from NREL nodal DG data.
    """)
    return


@app.cell
def _(pd):
    data = pd.read_csv("county_dg.csv.gz",index_col=[0],parse_dates=[0])
    return (data,)


@app.cell
def _(data, mo):
    _options = sorted(set([x.split()[-1] for x in data.columns]))
    state = mo.ui.dropdown(options=_options,value=_options[0],label="State:")
    return (state,)


@app.cell
def _(data, mo, state):
    _options = sorted([" ".join(x.split()[:-1]) for x in data.columns if x.endswith(f" {state.value}")])
    county = mo.ui.dropdown(options=_options,value=_options[0],label="County:")
    return (county,)


@app.cell
def _(county, mo, state):
    mo.hstack([state,county],justify='start')
    return


@app.cell
def _(county, data, mo, state):
    _plot = data[f"{county.value} {state.value}"].plot(
        grid=True,
        figsize=(10, 5),
        xlabel="Date/Time",
        ylabel="Solar DG [MW]",
        title=f"{county.value} {state.value}",
    )
    mo.mpl.interactive(_plot)
    return


@app.cell
def _(pd):
    dgen = (pd.read_csv("dgen.csv.gz",index_col=[0],parse_dates=[0])/1000).round(3)
    dgen.columns = [x.split("_")[0] for x in dgen.columns]
    return (dgen,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    The following nodes have no DG but probably should
    """)
    return


@app.cell
def _(dgen, pd):
    loads = pd.read_csv("https://raw.githubusercontent.com/eudoxys/wecc240/refs/heads/main/wecc240/gis/wecc240.csv",index_col="GEOHASH",usecols=["GEOHASH","NAME","GEN","LOAD"]).fillna(0).groupby(["GEOHASH","NAME"]).sum()
    loads = loads[loads.LOAD>0].reset_index().set_index("GEOHASH")

    missing_dg = list(set(loads.index) - set(dgen.columns))
    loads.loc[missing_dg].sort_index()
    return


@app.cell
def _():
    # county_nodes = pd.read_csv("https://github.com/eudoxys/wecc240/raw/refs/heads/main/wecc240/data/county_nodes.csv").set_index("node")
    # county_nodes[loads.loc[missing_dg].index]
    return


@app.cell
def _():
    import marimo as mo
    import pandas as pd

    return mo, pd


if __name__ == "__main__":
    app.run()
