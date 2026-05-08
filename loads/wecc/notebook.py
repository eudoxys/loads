import marimo

__generated_with = "0.19.7"
app = marimo.App(width="medium")


@app.cell
def _(mo):
    mo.md(r"""
    County-level solar DG retrodiction from NREL nodal DG data.
    """)
    return


@app.cell
def _(pd):
    data = pd.read_csv("county_dg.csv",index_col=[0],parse_dates=[0])
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
    _plot = data[f"{county.value} {state.value}"].plot(grid=True,figsize=(10,5),xlabel="Date/Time",ylabel="Solar DG [MW]",title=f"{county.value} {state.value}")
    mo.mpl.interactive(_plot)
    return


@app.cell
def _():
    import marimo as mo
    import pandas as pd
    return mo, pd


if __name__ == "__main__":
    app.run()
