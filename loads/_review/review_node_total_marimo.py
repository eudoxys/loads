import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    This notebook allows you to review the data in the `node_total.csv.gz` file.
    """)
    return


@app.cell
def _(pd):
    node_total = pd.read_csv("node_total.csv.gz",index_col=[0],parse_dates=[0])
    return (node_total,)


@app.cell
def _(mo, node_total):
    _options = sorted(node_total.index.year.unique())
    year_ui = mo.ui.dropdown(options=_options,label="Year:")
    return (year_ui,)


@app.cell
def _(calendar, mo, node_total, year_ui):
    _options = sorted(node_total.loc[node_total.index.year==year_ui.value].index.month.unique())
    _options = {calendar.month_name[x]:x for x in _options}
    month_ui = mo.ui.dropdown(options=_options,label="Month:",disabled=year_ui.value is None)
    return (month_ui,)


@app.cell
def _(mo, node_total):
    node_ui = mo.ui.dropdown(options=node_total.columns,label="Node:")
    return (node_ui,)


@app.cell
def _(mo, month_ui, node_ui, year_ui):
    mo.hstack([year_ui,month_ui,node_ui],justify="start")
    return


@app.cell
def _(node_ui):
    plot_options = dict(
        figsize=(10, 8),
        grid=True,
        title="WECC" if node_ui.value is None else node_ui.value,
        xlabel="Date/Time (UTC)",
        ylabel="Total load (GW)",
    )
    return (plot_options,)


@app.cell
def _(mo, month_ui, node_total, node_ui, plot_options, year_ui):
    _data = node_total.sum(axis=1) if node_ui.value is None else node_total[node_ui.value]
    if not year_ui.value is None:
        _data = _data.loc[_data.index.year==year_ui.value]
        if not month_ui.value is None:
            _data = _data.loc[_data.index.month==month_ui.value]
    mo.mpl.interactive((_data/1000).plot(**plot_options))
    return


@app.cell
def _():
    import marimo as mo
    import pandas as pd
    import calendar

    return calendar, mo, pd


if __name__ == "__main__":
    app.run()
