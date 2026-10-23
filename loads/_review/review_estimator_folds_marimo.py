"""Estimator holdout folds

This [marimo](https://marimo.io/) notebook reviews the holdout fold results
of `loads.estimator.Estimator` for any state and county, i.e., the result of
`Estimator(county_st,config=EstimatorConfig(holdout=...,fold=True))`.

Select a state, a county, and a holdout frequency `<N><F>`, then press
**Run**. The estimator is fit `N` times, once for each fold, so every valid
2018 hour is held out exactly once and its prediction is the out-of-fold
prediction from the model that did not see it. Fitting `N` models can take
several minutes, and the first run for a county also downloads its sector
loads and weather (NSRDB credentials are required).

The fold summary table shows the per-fold `MAE`, `RMSE` and `MAPE` reported by
the estimator in `attrs["folds"]`, together with the bias, $R^2$, the largest
absolute error, and the MAE and RMSE as a percent of the mean actual load. The
`mean` row is the average over the folds, as reported by the estimator, and
the `all` row pools all out-of-fold predictions. Times are UTC.
"""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="Estimator Holdout Folds")


@app.cell(hide_code=True)
def _(mo):
    mo.md(f"""
    ## {__doc__}
    """)
    return


@app.cell
def _(Counties):
    # state and county names
    _counties = Counties()
    states = sorted(_counties["ST"].unique())
    state_counties = {x:sorted(_counties.loc[_counties["ST"]==x,"COUNTY"]) for x in states}
    return state_counties, states


@app.cell
def _(mo, states):
    # state selection
    state_ui = mo.ui.dropdown(options=states,value="CA" if "CA" in states else states[0],label="State:")
    return (state_ui,)


@app.cell
def _(mo, state_counties, state_ui):
    # county selection
    _options = state_counties[state_ui.value]
    county_ui = mo.ui.dropdown(options=_options,
        value="Alameda" if "Alameda" in _options else _options[0],
        label="County:")
    return (county_ui,)


@app.cell
def _(mo):
    # holdout frequency and run button
    count_ui = mo.ui.number(start=2,stop=12,step=1,value=5,label="Folds (N):")
    interval_ui = mo.ui.radio(
        options={"Hours":"h","Days":"d","Weeks":"w","Months":"m"},
        value="Days",inline=True,label="Interval (F):")
    run_ui = mo.ui.run_button(label="Run")
    return count_ui, interval_ui, run_ui


@app.cell
def _(count_ui, county_ui, interval_ui, mo, run_ui, state_ui):
    mo.hstack([state_ui,county_ui,count_ui,interval_ui,run_ui],justify="start",align="center")
    return


@app.cell
def _(
    Estimator,
    EstimatorConfig,
    count_ui,
    county_ui,
    interval_ui,
    mo,
    run_ui,
    state_ui,
):
    # fit one model per fold
    mo.stop(not run_ui.value,
        mo.md("Choose a state, county and holdout frequency, then press **Run**."))
    county_st = f"{county_ui.value} {state_ui.value}"
    holdout = f"{count_ui.value}{interval_ui.value}"
    config = EstimatorConfig(holdout=holdout,fold=True)
    try:
        with mo.status.spinner(f"Fitting {count_ui.value} folds for {county_st}"):
            model = Estimator(county_st,config=config)
    except Exception as _err: # pylint: disable=broad-exception-caught
        mo.stop(True,mo.callout(mo.md(f"**{county_st}** ({holdout=}) failed: `{_err}`"),kind="danger"))
    title = f"{county_st}, holdout {holdout}"
    return model, title


@app.cell
def _(model, np, pd):
    # out-of-fold errors
    folds = sorted(int(x) for x in model["fold"].dropna().unique())
    results = model.loc[model["fold"].notna(),
        ["temperature_degF","humidity_pc","actual","prediction","fold"]].copy()
    results["fold"] = results["fold"].astype(int)
    results["error"] = results["prediction"] - results["actual"]

    def get_errors(df):
        """Error statistics of the valid rows of `df`"""
        _df = df.dropna(subset=["actual","prediction"])
        _error = _df.prediction - _df.actual
        _mean = _df.actual.mean()
        _sst = ((_df.actual - _mean)**2).sum()
        _mae = _error.abs().mean()
        _rmse = np.sqrt((_error**2).mean())
        return pd.Series({
            "rows": len(_df),
            "bias": _error.mean(),
            "R2": 1 - (_error**2).sum() / _sst if _sst > 0 else float("nan"),
            "max_error": _error.abs().max(),
            "MAE_pc_mean": _mae / _mean * 100,
            "RMSE_pc_mean": _rmse / _mean * 100,
            })
    return folds, get_errors, results


@app.cell
def _(folds, get_errors, model, pd, results):
    # fold summary
    _reported = model.attrs["folds"].copy()
    _reported.index = [str(x) for x in _reported.index]
    _extra = pd.DataFrame({str(k):get_errors(results[results.fold==k]) for k in folds}).T
    _extra.loc["mean"] = _extra.mean()
    summary = _reported.join(_extra)
    summary.loc["all",["MAE","RMSE","MAPE"]] = [
        results.error.abs().mean(),
        (results.error**2).mean()**0.5,
        (results.error/results.actual).abs().mean()*100,
        ]
    summary.loc["all",_extra.columns] = get_errors(results)
    summary["rows"] = summary["rows"].round().astype(int)
    summary.index.name = "fold"
    return (summary,)


@app.cell
def _(mo, model, results, summary, title):
    # holdout coverage check
    _held = model["fold"].notna().sum()
    _missing = int((model["actual"].notna() & model["fold"].isna()).sum())
    _kind = "success" if _missing == 0 else "info"
    mo.vstack([
        mo.md(f"### {title}"),
        mo.callout(mo.md(
            f"{_held} of {len(model)} hours were held out exactly once in "
            f"{len(summary)-2} folds; {_missing} hours with actual load have no "
            "out-of-fold prediction (missing weather or the weather lags at the start of the year). "
            f"Mean actual load {results.actual.mean():.1f} MW, peak {results.actual.max():.1f} MW."),
            kind=_kind),
        mo.ui.table(summary.round(3).reset_index(),selection=None,pagination=False,
            label="Holdout error by fold (MAE, RMSE, bias, max_error in MW; MAPE and *_pc_mean in %)"),
        ])
    return


@app.cell
def _(folds, mo):
    # fold and metric selection for the plots
    fold_ui = mo.ui.dropdown(options=["All"]+[str(x) for x in folds],value="All",label="Fold:")
    metric_ui = mo.ui.radio(options=["MAPE","MAE","RMSE","bias","R2"],value="MAPE",
        inline=True,label="Fold metric:")
    mo.hstack([fold_ui,metric_ui],justify="start")
    return fold_ui, metric_ui


@app.cell
def _(fold_ui, folds, plt, results):
    # selected rows and fold colors
    _cmap = plt.get_cmap("tab10" if len(folds) <= 10 else "tab20")
    colors = {k:_cmap(n) for n,k in enumerate(folds)}
    selected = folds if fold_ui.value == "All" else [int(fold_ui.value)]
    subset = results[results.fold.isin(selected)]
    return colors, selected, subset


@app.cell
def _(colors, plt, results, selected, title):
    # actual vs out-of-fold prediction
    _fig = plt.figure(figsize=(10,6))
    _ax = _fig.gca()
    for _k in sorted(results.fold.unique()):
        _data = results[results.fold==_k]
        _on = _k in selected
        _ax.plot(_data.actual,_data.prediction,".",markersize=2,
            color=colors[_k] if _on else "lightgrey",
            label=f"Fold {_k}" if _on else None,zorder=2 if _on else 1)
    _min,_max = results.actual.min(),results.actual.max()
    _ax.plot([_min,_max],[_min,_max],"k",label="Perfect prediction")
    _ax.legend(markerscale=4)
    _ax.grid()
    _ax.set_xlabel("Actual power (MW)")
    _ax.set_ylabel("Out-of-fold prediction (MW)")
    _ax.set_title(title)
    scatter_plot = _fig
    plt.close()
    return (scatter_plot,)


@app.cell
def _(colors, model, plt, selected, subset, title):
    # time series of actual and out-of-fold predictions
    _fig = plt.figure(figsize=(10,6))
    _ax = _fig.gca()
    _ax.plot(model.index,model.actual,"k",linewidth=0.5,label="Actual")
    for _k in selected:
        _data = subset[subset.fold==_k]
        _ax.plot(_data.index,_data.prediction,".",markersize=2,color=colors[_k],label=f"Fold {_k}")
    _ax.legend(markerscale=4)
    _ax.grid()
    _ax.set_xlabel("Date/Time (UTC)")
    _ax.set_ylabel("Power (MW)")
    _ax.set_title(title)
    timeseries_plot = _fig
    plt.close()
    return (timeseries_plot,)


@app.cell
def _(colors, folds, metric_ui, plt, selected, summary, title):
    # fold metric bar chart
    _metric = metric_ui.value
    _values = summary.loc[[str(x) for x in folds],_metric]
    _fig = plt.figure(figsize=(10,6))
    _ax = _fig.gca()
    _ax.bar([str(x) for x in folds],_values,
        color=[colors[x] if x in selected else "lightgrey" for x in folds])
    _ax.axhline(summary.loc["mean",_metric],color="k",linestyle="--",label="Mean of folds")
    _ax.axhline(summary.loc["all",_metric],color="r",linestyle=":",label="All out-of-fold rows")
    _ax.legend()
    _ax.grid(axis="y")
    _ax.set_xlabel("Fold")
    _ax.set_ylabel({"MAPE":"MAPE (%)","MAE":"MAE (MW)","RMSE":"RMSE (MW)",
        "bias":"Bias (MW)","R2":"$R^2$"}[_metric])
    _ax.set_title(title)
    metric_plot = _fig
    plt.close()
    return (metric_plot,)


@app.cell
def _(colors, folds, plt, results, title):
    # error distribution by fold
    _fig = plt.figure(figsize=(10,6))
    _ax = _fig.gca()
    _box = _ax.boxplot([results.error[results.fold==x] for x in folds],
        tick_labels=[str(x) for x in folds],patch_artist=True,showfliers=False)
    for _patch,_k in zip(_box["boxes"],folds):
        _patch.set_facecolor(colors[_k])
    _ax.axhline(0,color="k",linewidth=0.5)
    _ax.grid(axis="y")
    _ax.set_xlabel("Fold")
    _ax.set_ylabel("Prediction error (MW)")
    _ax.set_title(f"{title} (whiskers 1.5 IQR, outliers not shown)")
    error_plot = _fig
    plt.close()
    return (error_plot,)


@app.cell
def _(plt, subset, title):
    # mean error by month and hour of day
    _table = subset.pivot_table(index=subset.index.hour,columns=subset.index.month,
        values="error",aggfunc="mean")
    _limit = max(abs(_table.min().min()),abs(_table.max().max()))
    _fig = plt.figure(figsize=(10,6))
    _ax = _fig.gca()
    _image = _ax.imshow(_table.values,aspect="auto",origin="lower",cmap="RdBu_r",
        vmin=-_limit,vmax=_limit,
        extent=[_table.columns.min()-0.5,_table.columns.max()+0.5,-0.5,23.5])
    _fig.colorbar(_image,ax=_ax,label="Mean prediction error (MW)")
    _ax.set_xticks(_table.columns)
    _ax.set_xlabel("Month")
    _ax.set_ylabel("Hour of day (UTC)")
    _ax.set_title(title)
    heatmap_plot = _fig
    plt.close()
    return (heatmap_plot,)


@app.cell
def _(colors, plt, selected, subset, title):
    # error vs weather
    _fig,_axes = plt.subplots(1,2,figsize=(10,5),sharey=True)
    for _ax,_column,_label in zip(_axes,
            ["temperature_degF","humidity_pc"],
            [r"Temperature ($^\circ$F)","Relative humidity (%)"]):
        for _k in selected:
            _data = subset[subset.fold==_k]
            _ax.plot(_data[_column],_data.error,".",markersize=2,color=colors[_k],label=f"Fold {_k}")
        _ax.axhline(0,color="k",linewidth=0.5)
        _ax.grid()
        _ax.set_xlabel(_label)
    _axes[0].set_ylabel("Prediction error (MW)")
    _axes[0].legend(markerscale=4)
    _fig.suptitle(title)
    weather_plot = _fig
    plt.close()
    return (weather_plot,)


@app.cell
def _(
    error_plot,
    heatmap_plot,
    metric_plot,
    mo,
    scatter_plot,
    timeseries_plot,
    weather_plot,
):
    mo.ui.tabs({
        "Scatter": mo.mpl.interactive(scatter_plot),
        "Timeseries": mo.mpl.interactive(timeseries_plot),
        "Fold metric": mo.mpl.interactive(metric_plot),
        "Error distribution": mo.mpl.interactive(error_plot),
        "Error by hour/month": mo.mpl.interactive(heatmap_plot),
        "Error vs weather": mo.mpl.interactive(weather_plot),
    })
    return


@app.cell
def _():
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    from fips.counties import Counties
    from loads.estimator import Estimator, EstimatorConfig

    return Counties, Estimator, EstimatorConfig, mo, np, pd, plt


if __name__ == "__main__":
    app.run()
