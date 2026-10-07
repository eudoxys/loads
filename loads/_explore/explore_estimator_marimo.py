import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    This notebook reviews the results of running the `explore_estimator.py` scripts, which sweeps the yearly, weekly, and daily harmonics and evaluates the MAE, RMSE, MAPE, and R2 of the estimator's performance on the holdout test.
    """)
    return


@app.cell
def _(county_ui, mo, reload_ui):
    mo.hstack([county_ui,reload_ui])
    return


@app.cell
def _(mo, x_ui, y_ui, z_ui):
    mo.hstack([mo.md("**Plot axes**"),x_ui,y_ui,z_ui])
    return


@app.cell
def _(county_ui, data, mo, x_ui, y_ui):
    w_axis = list(set(["yearly","weekly","daily"]) - set([x_ui.value,y_ui.value]))
    _options = [float(x) for x in set(data.loc[county_ui.value,w_axis].values.T[0])]
    w_ui = mo.ui.slider(steps=_options,label=w_axis[0].title() + " harmonics",show_value=True)
    w_ui
    return w_axis, w_ui


@app.cell
def _(alt, county_ui, data, w_axis, w_ui, x_ui, y_ui, z_ui):
    # replace _df with your data source
    _chart = (
        alt.Chart(data.loc[county_ui.value].set_index(w_axis).loc[w_ui.value])
        .mark_rect()
        .encode(
            x=alt.X(field=x_ui.value, type='nominal'),
            y=alt.Y(field=y_ui.value, type='nominal'),
            color=alt.Color(field=z_ui.value, type='quantitative'),
            tooltip=[
                alt.Tooltip(field="yearly", format=',.0f'),
                alt.Tooltip(field="weekly", format=',.0f'),
                alt.Tooltip(field="daily", format=',.0f'),
                alt.Tooltip(field=z_ui.value, format=',.2f')
            ]
        )
        .properties(
            height=290,
            width='container',
            config={
                'axis': {
                    'grid': False
                }
            }
        )
    )
    _chart
    return


@app.cell
def _(mo):
    reload_ui = mo.ui.button(label="Reload data")
    return (reload_ui,)


@app.cell
def _(pd, reload_ui):
    reload_ui.value
    data = pd.read_csv("explore_estimator.csv",index_col=[0])
    return (data,)


@app.cell
def _(data, mo):
    _options = sorted(data.index.unique(),key=lambda x:(x.split()[-1],x.split()[:-1]))
    county_ui = mo.ui.dropdown(options=_options,value=_options[0],label="**County**:")
    return (county_ui,)


@app.cell
def _(data, mo):
    _options = {x.title():x for x in data.columns[0:3]}
    x_ui = mo.ui.radio(_options,label="**X**:",inline=True,value=list(_options)[0])
    y_ui = mo.ui.radio(_options,label="**Y**:",inline=True,value=list(_options)[1])
    return x_ui, y_ui


@app.cell
def _(data, mo):
    _options = {x.upper():x for x in data.columns[3:]}
    z_ui = mo.ui.radio(_options,label="**Z**:",inline=True,value=list(_options)[0])
    return (z_ui,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    The following are the best results for the harmonic sweep.
    """)
    return


@app.cell
def _(mo):
    best_ui = mo.ui.slider(steps=range(0,9),label="Accept most parsimonious harmonics that are within",value=1)
    return (best_ui,)


@app.cell
def _(best_ui, mo):
    mo.hstack([best_ui,mo.md(f"{best_ui.value}% of minimum observed")],justify='start')
    return


@app.cell
def _():
    return


@app.cell
def _(best_ui, county_ui, data, pd):
    _df = data.loc[county_ui.value].sort_values(["yearly","weekly","daily"]).round(3)
    _best = {}
    for _metric in ["mae","rmse","mape"]:
        _min = _df[_metric].min()
        _cutoff = _min*(1+best_ui.value/100)
        _selected = _df[_df[_metric]<=_cutoff][["yearly","weekly","daily",_metric]].sort_values(["daily","weekly","yearly"])
        _best[_metric] = list(_selected.values[0])
        _best[_metric].append(_cutoff.round(3))
        _best[_metric].append(_min)
    _result = pd.DataFrame(data=_best,index=["yearly","weekly","daily","value","cutoff","min"]).T
    _result.index.name = "metric"
    _result.reset_index(inplace=True)
    _result["county"] = county_ui.value
    _result.set_index(["county","metric"])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    If a selection of harmonics is at the upper limit of a sweep range then the range should be expanded to ensure that the best values are checked. The sweep ranges are as follows.
    """)
    return


@app.cell
def _(county_ui, data, pd):
    _df = pd.DataFrame(
        data={
            "min":data.loc[county_ui.value][["yearly","weekly","daily"]].min(),
            "max":data.loc[county_ui.value][["yearly","weekly","daily"]].max(),
        })
    _df["county"] = county_ui.value
    _df.index.name = "metric"
    _df.reset_index(inplace=True)
    _df.set_index(["county","metric"])
    return


@app.cell
def _():
    import marimo as mo
    import pandas as pd
    import altair as alt
    import IPython

    return alt, mo, pd


if __name__ == "__main__":
    app.run()
