"""WECC county load calibrated to EIA-930, by state

This [marimo](https://marimo.io/) notebook reviews the WECC county net loads
calibrated to the EIA-930 demand of the US WECC balancing authorities (BAs)
with `loads.calibrate.CalibrateForm930`, compared with the uncalibrated
county net load estimate (`loads/wecc/wecc_estimate.csv.gz` minus
`loads/wecc/county_dg_scaled.csv.gz`, clipped at zero). The inputs are those
of `loads/_validate/validate_calibrate_form930.py`.

Select a state and, optionally, a county, a year and a month (the
calibration runs on the selected window only; "All" uses 2018–2022, and the
month is used only with a year). For each county the notebook reports:

  - the calibration scale and offset: the least-squares fit
    $X_u(t)\\approx a_uL_u(t)+b_u$ of the calibrated load $X$ to the
    estimate $L$ over the window. `CalibrateForm930` itself scales each
    county's BA shares hour by hour, so $a$ and $b$ summarize that map
    rather than define it; `energy_ratio` is $\\sum X/\\sum L$;

  - the energy and peak power of the estimate and of the calibrated load;

  - MAPE, MAE, RMSE and R² of the calibrated load relative to the estimate
    (hours with a `NaN` calibrated load are excluded, and MAPE also
    excludes hours with zero estimate).
"""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="WECC Calibrated County Load")


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
        load,factors,demand,_ = validation.inputs()
    return demand, factors, load


@app.cell
def _(load, mo):
    # state and time window selection
    _states = sorted({x.rsplit(" ",1)[1] for x in load.columns})
    state_ui = mo.ui.dropdown(options=_states,value="CA" if "CA" in _states else _states[0],label="State:")
    year_ui = mo.ui.dropdown(options=["All"]+sorted({str(x) for x in load.index.year}),
        value="All",label="Year:")
    month_ui = mo.ui.dropdown(options=["All"]+[f"{x:02d}" for x in range(1,13)],
        value="All",label="Month:")
    return month_ui, state_ui, year_ui


@app.cell
def _(load, mo, state_ui):
    # county selection
    _counties = sorted(x.rsplit(" ",1)[0] for x in load.columns if x.endswith(f" {state_ui.value}"))
    county_ui = mo.ui.dropdown(options=_counties,value=None,label="County:")
    return (county_ui,)


@app.cell
def _(county_ui, mo, month_ui, state_ui, year_ui):
    mo.hstack([state_ui,county_ui,year_ui,month_ui],justify="start")
    return


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
def _(CalibrateForm930, demand, factors, load, mo, window):
    # calibrate all counties over the window (BAs cross state lines)
    with mo.status.spinner("Calibrating counties"):
        result = CalibrateForm930(load.loc[window],factors,demand.loc[window])
    return (result,)


@app.cell
def _(county_ui, load, np, pd, result, state_ui, window):
    # county statistics for the selected state
    columns = [x for x in result.columns if x.endswith(f" {state_ui.value}")]
    selected = columns if county_ui.value is None else [f"{county_ui.value} {state_ui.value}"]
    estimate = load.loc[window,columns]
    calibrated = pd.DataFrame(result)[columns]

    def _stats(x,y):
        """Fit and error statistics of calibrated y relative to estimate x"""
        ok = y.notna()
        x,y = x[ok].values,y[ok].values
        if x.size == 0:
            return {}
        if np.ptp(x) > 0:
            a,b = np.polyfit(x,y,1)
        else:
            a,b = (np.nan,float(np.mean(y)-np.mean(x)))
        err = y - x
        nz = x != 0
        ss = float(np.square(x - x.mean()).sum())
        return {
            "scale":a,
            "offset_MW":b,
            "energy_ratio":y.sum()/x.sum() if x.sum() > 0 else np.nan,
            "MAPE_pc":100*float(np.mean(np.abs(err[nz]/x[nz]))) if nz.any() else np.nan,
            "MAE_MW":float(np.mean(np.abs(err))),
            "RMSE_MW":float(np.sqrt(np.mean(np.square(err)))),
            "R2":1 - float(np.square(err).sum())/ss if ss > 0 else np.nan,
            "hours":int(x.size),
            }

    _rows = []
    for _name in columns:
        _x,_y = estimate[_name],calibrated[_name]
        _f = result.factors.loc[_name] if _name in result.factors.index else pd.Series(dtype=float)
        _rows.append({
            "county_st":_name,
            "bas":", ".join(f"{b} {v:.3g}" for b,v in _f[_f > 0].items()),
            "estimate_MWh":_x.sum(),
            "calibrated_MWh":_y.sum(),
            "energy_change_pc":100*(_y.sum()/_x.sum()-1) if _x.sum() > 0 else np.nan,
            "estimate_peak_MW":_x.max(),
            "estimate_peak_time":_x.idxmax(),
            "calibrated_peak_MW":_y.max(),
            "calibrated_peak_time":_y.idxmax() if _y.notna().any() else pd.NaT,
            "peak_change_pc":100*(_y.max()/_x.max()-1) if _x.max() > 0 else np.nan,
            **_stats(_x,_y),
            })
    county_table = pd.DataFrame(_rows).set_index("county_st")
    _x,_y = estimate[selected].sum(axis=1),calibrated[selected].sum(axis=1,min_count=len(selected))
    total_stats = {
        "estimate_MWh":_x.sum(),"calibrated_MWh":_y.sum(),
        "estimate_peak_MW":_x.max(),"calibrated_peak_MW":_y.max(),
        **_stats(_x,_y),
        }
    return calibrated, county_table, estimate, selected, total_stats


@app.cell
def _(county_ui, mo, period, result, selected, state_ui, total_stats):
    # summary of the selection
    _label = state_ui.value if county_ui.value is None else f"{county_ui.value} {state_ui.value}"
    _bas = result.factors.loc[[x for x in selected if x in result.factors.index]]
    _bas = sorted(_bas.columns[(_bas > 0).any()])
    _s = total_stats
    mo.vstack([
        mo.md(f"### {_label}, {period} ({len(selected)} counties)"),
        mo.hstack([
            mo.stat(f"{_s['calibrated_MWh']/1e6:,.2f} TWh",label="Calibrated energy",
                caption=f"estimate {_s['estimate_MWh']/1e6:,.2f} TWh"
                    f" ({100*(_s['energy_ratio']-1):+.1f}%)"),
            mo.stat(f"{_s['calibrated_peak_MW']:,.0f} MW",label="Calibrated peak",
                caption=f"estimate {_s['estimate_peak_MW']:,.0f} MW"),
            mo.stat(f"{_s['scale']:.3f}",label="Scale",caption=f"offset {_s['offset_MW']:,.1f} MW"),
            mo.stat(f"{_s['MAPE_pc']:.1f}%",label="MAPE",caption=f"MAE {_s['MAE_MW']:,.1f} MW"),
            mo.stat(f"{_s['RMSE_MW']:,.1f} MW",label="RMSE",caption=f"R² {_s['R2']:.3f}"),
        ],justify="start"),
        mo.md("**BAs serving the selection:** " + ", ".join(_bas)
            + (f"  \n**Uncalibrated BAs** (keep the estimate): {', '.join(x for x in result.uncalibrated if x in _bas)}"
                if set(result.uncalibrated) & set(_bas) else "")),
    ])
    return


@app.cell
def _(calibrated, county_ui, estimate, mo, period, plt, selected, state_ui):
    # estimate vs calibrated load plot
    _x = estimate[selected].sum(axis=1)
    _y = calibrated[selected].sum(axis=1,min_count=len(selected))
    _label = state_ui.value if county_ui.value is None else f"{county_ui.value} {state_ui.value}"
    plt.close()
    _fig,_ax = plt.subplots(figsize=(10,4))
    _width = 0.6 if len(_x) > 744 else 1.0
    _x.plot(ax=_ax,linewidth=_width,label="estimate",alpha=0.8)
    _y.plot(ax=_ax,linewidth=_width,label="calibrated",alpha=0.8)
    _ax.set_ylabel("Net load (MW)")
    _ax.set_xlabel("Date/Time (UTC)")
    _ax.set_title(f"{_label}, {period}")
    _ax.grid(alpha=0.3)
    _ax.legend()
    plt.close()
    _fig2,_ax2 = plt.subplots(figsize=(5,5))
    _ax2.scatter(_x,_y,s=2,alpha=0.3)
    _lim = [0,max(_x.max(),_y.max())*1.05]
    _ax2.plot(_lim,_lim,color="k",linewidth=0.5)
    _ax2.set_xlim(_lim)
    _ax2.set_ylim(_lim)
    _ax2.set_xlabel("Estimate (MW)")
    _ax2.set_ylabel("Calibrated (MW)")
    _ax2.grid(alpha=0.3)
    plot_tabs = {"Time series":_fig,"Scatter":_fig2}
    mo.md("")
    return (plot_tabs,)


@app.cell
def _(county_table, hourly_table, mo, plot_tabs, result, selected):
    # tables
    _table = county_table.loc[selected].round({
        "estimate_MWh":0,"calibrated_MWh":0,"energy_change_pc":2,
        "estimate_peak_MW":1,"calibrated_peak_MW":1,"peak_change_pc":2,
        "scale":4,"offset_MW":2,"energy_ratio":4,
        "MAPE_pc":2,"MAE_MW":2,"RMSE_MW":2,"R2":4,
        }).reset_index()
    _bas = result.factors.loc[[x for x in selected if x in result.factors.index]]
    _bas = list(_bas.columns[(_bas > 0).any()])
    _scale = result.scale[_bas].describe().T[["mean","min","50%","max"]]\
        .rename({"50%":"median"},axis=1).round(4).rename_axis("ba").reset_index()
    mo.ui.tabs({
        **plot_tabs,
        "Counties":mo.ui.table(_table,page_size=25,selection=None),
        "BA scale":mo.vstack([
            mo.md("Hourly BA scale factor $D_b/S_b$ over the window (1 for BAs without demand)."),
            mo.ui.table(_scale,selection=None)]),
        "Hourly data":mo.ui.table(hourly_table(selected),page_size=24,selection=None),
    })
    return


@app.cell
def _(calibrated, estimate, pd):
    # hourly estimate and calibrated loads of the selection
    def hourly_table(columns):
        return pd.concat({"estimate":estimate[columns],"calibrated":calibrated[columns]},axis=1)\
            .swaplevel(axis=1).sort_index(axis=1).round(2)\
            .pipe(lambda x: x.set_axis([f"{a} {b}" for a,b in x.columns],axis=1))
    return (hourly_table,)


@app.cell
def _():
    import marimo as mo
    import importlib.util
    import pathlib
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from loads.calibrate import CalibrateForm930

    return CalibrateForm930, importlib, mo, np, pathlib, pd, plt


if __name__ == "__main__":
    app.run()
