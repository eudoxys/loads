"""Validate the calibrated 2020 load against the CAISO reported load

Run with

    marimo edit loads/_validate/validate_calibrate_marimo.py

The notebook compares the CAISO-region net load of the calibrated 2020 WECC
county loads with the hourly load CAISO reported for 2020
(`loads/caiso/2020.csv`). The calibration uses the default settings of
`loads/_explore/explore_calibrate_marimo.py`: DG from
`loads/wecc/county_dg_scaled.csv.gz`, the monthly state energy and CAISO/WECC peak
targets and the CAISO/WECC membership in `loads/_test/data`, and the
predeclared weight search and selection rule of `loads.calibrate.Calibrate`.

The 2020 load matrix and the calibration are read from the local cache.
Build them first with

    python loads/_validate/validate_calibrate.py

or use the buttons in the notebook.
"""

import marimo

__generated_with = "0.25.0"
app = marimo.App(width="full")


@app.cell
def _():
    import sys
    from contextlib import ExitStack
    from pathlib import Path

    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    sys.path.insert(0,str(Path(__file__).resolve().parent))
    import validate_calibrate as vc

    return ExitStack, mo, np, pd, plt, vc


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Calibration validation

    **Calibrated 2020 WECC county loads against the CAISO reported load**

    The CAISO-region net load of the calibrated county loads, $\sum_j
    g_j\,(L_{tj}-D_{tj})$, is compared hour by hour with the load CAISO
    reported for 2020. The uncalibrated TSGAM prediction, $\sum_j
    g_j\,(X_{tj}-D_{tj})$, is shown for reference. CAISO reports metered
    load, which is net of behind-the-meter generation, so the net load is
    the comparable quantity.
    """)
    return


@app.cell
def _(pd, vc):
    YEAR = vc.YEAR
    TZ = "America/Los_Angeles"
    MONTHS = pd.date_range(f"{YEAR}-01-01",periods=12,freq="MS")
    energy_target,peak_target = vc.targets(YEAR)
    return TZ, YEAR, peak_target


@app.cell
def _(mo):
    build_button = mo.ui.run_button(label="Build load matrix")
    calibrate_button = mo.ui.run_button(label="Run calibration")
    return build_button, calibrate_button


@app.cell
def _(ExitStack, YEAR, build_button, mo, vc):
    _cache = vc.load_cache(YEAR)
    _run = build_button.value or mo.app_meta().mode == "script"
    _note = ""
    if not _cache.download() and not _run:
        _missing = vc.missing_inputs(YEAR)
        _note = (f" The cache lacks the training data or weather of {len(_missing)} WECC "
            f"counties (e.g. {_missing[0]}), which will be downloaded and can take hours."
            if _missing else " All the county inputs are in the cache.")
    mo.stop(not _cache.download() and not _run,mo.vstack([
        mo.callout(mo.md(
            f"The {YEAR} load matrix is not in the cache. Build it with "
            "`python loads/_validate/validate_calibrate.py` and rerun this "
            f"notebook, or press **Build load matrix** to run the 407 county "
            f"predictions here.{_note}"),kind="warn"),
        build_button,
        ]))
    with ExitStack() as _stack:
        _bar = {}
        def _progress(done,total,unit):
            if not _bar:
                _bar["bar"] = _stack.enter_context(mo.status.progress_bar(
                    total=total,title="County predictions",
                    completion_title="County predictions complete"))
            _bar["bar"].update(subtitle=unit)
        load = vc.gross_load(YEAR,progress=_progress)
    dg = vc.distributed_generation(load)
    regions = vc.membership(list(load.columns))
    return dg, load, regions


@app.cell
def _(ExitStack, YEAR, calibrate_button, mo, vc):
    _caches = vc.result_caches(YEAR)
    _cached = all(x.download() for x in _caches.values())
    mo.stop(not _cached and not (calibrate_button.value or mo.app_meta().mode == "script"),mo.vstack([
        mo.callout(mo.md(
            f"The {YEAR} calibration is not in the cache. Run "
            "`python loads/_validate/validate_calibrate.py` and rerun this "
            "notebook, or press **Run calibration** to search the weight grid "
            "for each month here."),kind="warn"),
        calibrate_button,
        ]))
    with ExitStack() as _stack:
        _bar = {}
        def _progress(done,total,info):
            if not _bar:
                _bar["bar"] = _stack.enter_context(mo.status.progress_bar(
                    total=total,title="Calibration",completion_title="Calibration complete"))
            _bar["bar"].update(subtitle=f"{info['block']:%B}: {info['step']} "
                f"{info.get('candidate','')} ({info['status']})")
        calibration = vc.calibrated_load(YEAR,progress=_progress)
    shaped = calibration["load"]
    return calibration, shaped


@app.cell
def _(YEAR, dg, load, pd, regions, shaped, vc):
    caiso = vc.caiso_load(YEAR)
    _weight = regions["CAISO"]
    _model = pd.DataFrame({
        "input": (load - dg) @ _weight,
        "calibrated": (shaped.reindex(load.index) - dg) @ _weight,
        "gross": shaped.reindex(load.index) @ _weight,
        "dg": dg @ _weight,
        })
    hourly = caiso[["CAISO"]].rename(columns={"CAISO":"reported"}).join(_model,how="inner").dropna()
    hourly["month"] = hourly.index.tz_convert("UTC").tz_localize(None).to_period("M")
    return (hourly,)


@app.cell
def _(np, pd):
    def metrics(model,actual,tz):
        """Hourly fit of a model series to the reported series"""
        error = model - actual
        rmse = float(np.sqrt(np.mean(np.square(error))))
        peak = model.idxmax()
        return {
            "Energy (GWh)": model.sum() / 1e3,
            "Energy error (%)": 100 * error.sum() / actual.sum(),
            "Peak (MW)": model.max(),
            "Peak error (%)": 100 * (model.max() - actual.max()) / actual.max(),
            "Peak hour (local)": f"{peak.tz_convert(tz):%b %d %H:%M}",
            "MAPE (%)": 100 * float(np.mean(np.abs(error) / actual)),
            "RMSE (MW)": rmse,
            "CV(RMSE) (%)": 100 * rmse / actual.mean(),
            "Bias (MW)": error.mean(),
            "R²": 1 - float(np.sum(np.square(error)) / np.sum(np.square(actual - actual.mean()))),
            "Correlation": float(np.corrcoef(model,actual)[0,1]),
            }

    def fmt(table,digits):
        """Format a metrics table for display"""
        return pd.DataFrame({column:[x if isinstance(x,str) else f"{x:,.{digits.get(column,1)}f}"
            for x in table[column]] for column in table.columns},index=table.index)

    return fmt, metrics


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Overall fit

    Hourly fit of the CAISO-region net load over the hours common to the
    model year (UTC) and the CAISO reporting year (Pacific time).
    """)
    return


@app.cell
def _(TZ, hourly, metrics, pd):
    overall = pd.DataFrame({
        "CAISO reported": metrics(hourly.reported,hourly.reported,TZ),
        "TSGAM input": metrics(hourly.input,hourly.reported,TZ),
        "Calibrated": metrics(hourly.calibrated,hourly.reported,TZ),
        }).T
    return (overall,)


@app.cell
def _(hourly, mo, overall):
    _row = overall.loc["Calibrated"]
    _input = overall.loc["TSGAM input"]
    mo.vstack([
        mo.hstack([
            mo.stat(f"{_row['MAPE (%)']:.2f}%",label="MAPE",
                caption=f"TSGAM input {_input['MAPE (%)']:.2f}%",bordered=True),
            mo.stat(f"{_row['CV(RMSE) (%)']:.2f}%",label="CV(RMSE)",
                caption=f"TSGAM input {_input['CV(RMSE) (%)']:.2f}%",bordered=True),
            mo.stat(f"{_row['Energy error (%)']:+.2f}%",label="Energy error",
                caption=f"TSGAM input {_input['Energy error (%)']:+.2f}%",bordered=True),
            mo.stat(f"{_row['Peak error (%)']:+.2f}%",label="Peak error",
                caption=f"{_row['Peak (MW)']:,.0f} MW vs {hourly.reported.max():,.0f} MW reported",bordered=True),
            mo.stat(f"{_row['R²']:.3f}",label="R²",
                caption=f"TSGAM input {_input['R²']:.3f}",bordered=True),
            ],widths="equal",gap=0.75),
        mo.md(f"{len(hourly):,} hours from {hourly.index[0]:%Y-%m-%d %H:%M} to "
            f"{hourly.index[-1]:%Y-%m-%d %H:%M} UTC"),
        ],gap=0.5)
    return


@app.cell
def _(fmt, mo, overall):
    mo.ui.table(fmt(overall,{"Energy (GWh)":0,"Peak (MW)":0,"RMSE (MW)":0,"Bias (MW)":0,
        "MAPE (%)":2,"CV(RMSE) (%)":2,"Energy error (%)":2,"Peak error (%)":2,"R²":4,"Correlation":4}),
        selection=None,show_column_summaries=False,show_data_types=False,
        show_download=False,show_search=False)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Monthly fit

    Calibration blocks are calendar months in UTC, so the months here are
    UTC months too. The CAISO ceiling is the peak target the calibration
    drives each month's CAISO net-load peak to.
    """)
    return


@app.cell
def _(TZ, hourly, metrics, pd, peak_target):
    _ceiling = peak_target["CAISO"].copy()
    _ceiling.index = _ceiling.index.tz_localize(None).to_period("M")
    _rows = {}
    for _month,_group in hourly.groupby("month"):
        _fit = metrics(_group.calibrated,_group.reported,TZ)
        _rows[_month] = {
            "Reported energy (GWh)": _group.reported.sum() / 1e3,
            "Input energy (GWh)": _group.input.sum() / 1e3,
            "Calibrated energy (GWh)": _fit["Energy (GWh)"],
            "Energy error (%)": _fit["Energy error (%)"],
            "Reported peak (MW)": _group.reported.max(),
            "Input peak (MW)": _group.input.max(),
            "Calibrated peak (MW)": _fit["Peak (MW)"],
            "CAISO ceiling (MW)": _ceiling.get(_month,float("nan")),
            "Peak error (%)": _fit["Peak error (%)"],
            "MAPE (%)": _fit["MAPE (%)"],
            "Input MAPE (%)": metrics(_group.input,_group.reported,TZ)["MAPE (%)"],
            "CV(RMSE) (%)": _fit["CV(RMSE) (%)"],
            "R²": _fit["R²"],
            }
    monthly = pd.DataFrame(_rows).T
    monthly.index.name = "Month"
    return (monthly,)


@app.cell
def _(fmt, mo, monthly):
    _table = fmt(monthly,{"Energy error (%)":2,"Peak error (%)":2,"MAPE (%)":2,"Input MAPE (%)":2,
        "CV(RMSE) (%)":2,"R²":3} | {x:0 for x in monthly.columns if "GWh" in x or "MW" in x})
    _table.index = monthly.index
    mo.ui.table(_table.reset_index(names="Month"),selection=None,show_column_summaries=False,
        show_data_types=False,show_download=True,show_search=False,page_size=12)
    return


@app.cell
def _(monthly, np, plt):
    _figure,_axes = plt.subplots(1,2,figsize=(14,4.2),constrained_layout=True)
    _x = np.arange(len(monthly))
    _labels = monthly.index
    for _offset,(_column,_label) in zip([-0.27,0,0.27],[
            ("Reported energy (GWh)","CAISO reported"),
            ("Input energy (GWh)","TSGAM input"),
            ("Calibrated energy (GWh)","Calibrated")]):
        _axes[0].bar(_x + _offset,monthly[_column],width=0.27,label=_label)
    _axes[0].set_ylabel("Net-load energy (GWh)")
    _axes[0].set_title("Monthly energy",loc="left")
    for _column,_label,_style in [
            ("Reported peak (MW)","CAISO reported","o-"),
            ("Input peak (MW)","TSGAM input","s-"),
            ("Calibrated peak (MW)","Calibrated","^-")]:
        _axes[1].plot(_x,monthly[_column],_style,label=_label)
    _axes[1].plot(_x,monthly["CAISO ceiling (MW)"],"k--",linewidth=1.0,label="CAISO ceiling")
    _axes[1].set_ylabel("Net-load peak (MW)")
    _axes[1].set_title("Monthly peak",loc="left")
    for _axis in _axes:
        _axis.set_xticks(_x,_labels)
        _axis.grid(True,axis="y",linewidth=0.5,alpha=0.4)
        _axis.legend(loc="best",fontsize=9)
    _figure
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Hourly profiles
    """)
    return


@app.cell
def _(hourly, mo):
    _options = {"Whole year":"all"} | {x.to_timestamp().strftime("%B %Y"):str(x) for x in hourly.month.unique()}
    period_ui = mo.ui.dropdown(options=_options,value="Whole year",label="Period")
    period_ui
    return (period_ui,)


@app.cell
def _(TZ, hourly, period_ui, plt):
    _data = hourly if period_ui.value == "all" else hourly[hourly.month.astype(str) == period_ui.value]
    _local = _data.index.tz_convert(TZ).tz_localize(None)
    _figure,_axes = plt.subplots(2,1,figsize=(14,6.5),sharex=True,constrained_layout=True,
        gridspec_kw={"height_ratios":[3,1.4]})
    _width = 0.6 if period_ui.value == "all" else 1.0
    _axes[0].plot(_local,_data.reported,linewidth=_width,color="black",label="CAISO reported")
    _axes[0].plot(_local,_data.input,linewidth=_width,alpha=0.7,label="TSGAM input")
    _axes[0].plot(_local,_data.calibrated,linewidth=_width,alpha=0.85,label="Calibrated")
    _axes[0].set_ylabel("Net load (MW)")
    _axes[0].legend(ncols=3,loc="upper left")
    _axes[1].plot(_local,_data.input - _data.reported,linewidth=_width,alpha=0.7,label="TSGAM input")
    _axes[1].plot(_local,_data.calibrated - _data.reported,linewidth=_width,alpha=0.85,label="Calibrated")
    _axes[1].axhline(0,color="black",linewidth=0.8)
    _axes[1].set_ylabel("Error (MW)")
    _axes[1].set_xlabel("Pacific time")
    for _axis in _axes:
        _axis.grid(True,linewidth=0.5,alpha=0.4)
    _figure
    return


@app.cell
def _(hourly, np, plt):
    _figure,_axes = plt.subplots(1,3,figsize=(15,4.6),constrained_layout=True)
    _low = min(hourly[["reported","input","calibrated"]].min())
    _high = max(hourly[["reported","input","calibrated"]].max())
    for _axis,_column,_title in zip(_axes[:2],["input","calibrated"],["TSGAM input","Calibrated"]):
        _axis.hexbin(hourly.reported,hourly[_column],gridsize=60,bins="log",cmap="viridis",mincnt=1,
            extent=(_low,_high,_low,_high))
        _axis.plot([_low,_high],[_low,_high],"r-",linewidth=1.0)
        _axis.set_xlabel("CAISO reported (MW)")
        _axis.set_ylabel(f"{_title} (MW)")
        _axis.set_title(f"{_title} vs reported",loc="left")
        _axis.set_aspect("equal")
    _duration = 100 * np.arange(1,len(hourly) + 1) / len(hourly)
    for _column,_label,_style in [("reported","CAISO reported","k-"),
            ("input","TSGAM input","-"),("calibrated","Calibrated","-")]:
        _axes[2].plot(_duration,np.sort(hourly[_column].values)[::-1],_style,linewidth=1.2,label=_label)
    _axes[2].set_xlabel("Hours exceeded (%)")
    _axes[2].set_ylabel("Net load (MW)")
    _axes[2].set_title("Load duration",loc="left")
    _axes[2].grid(True,linewidth=0.5,alpha=0.4)
    _axes[2].legend(loc="upper right")
    _figure
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Daily shape

    Mean net load by hour of the day (Pacific time) for each month, and the
    mean calibrated error by hour and month relative to the mean reported
    load of that hour and month.
    """)
    return


@app.cell
def _(TZ, hourly):
    _local = hourly.index.tz_convert(TZ)
    profiles = hourly[["reported","input","calibrated"]].groupby(
        [hourly.month.values,_local.hour]).mean()
    profiles.index.names = ["month","hour"]
    return (profiles,)


@app.cell
def _(plt, profiles):
    _months = profiles.index.get_level_values("month").unique()
    _columns = 4
    _rows = int((len(_months) + _columns - 1) // _columns)
    _figure,_axes = plt.subplots(_rows,_columns,figsize=(15,2.9*_rows),sharex=True,sharey=True,
        constrained_layout=True,squeeze=False)
    for _axis,_month in zip(_axes.flat,_months):
        _data = profiles.loc[_month]
        _axis.plot(_data.index,_data.reported,"k-",linewidth=1.4,label="CAISO reported")
        _axis.plot(_data.index,_data.input,"-",linewidth=1.0,label="TSGAM input")
        _axis.plot(_data.index,_data.calibrated,"-",linewidth=1.2,label="Calibrated")
        _axis.set_title(_month,loc="left",fontsize=10)
        _axis.grid(True,linewidth=0.5,alpha=0.4)
        _axis.set_xticks([0,6,12,18,23])
    for _axis in list(_axes.flat)[len(_months):]:
        _axis.set_visible(False)
    _axes.flat[0].legend(fontsize=8,loc="upper left")
    _figure.supxlabel("Hour of day (Pacific time)")
    _figure.supylabel("Mean net load (MW)")
    _figure
    return


@app.cell
def _(np, plt, profiles):
    _error = 100 * (profiles.calibrated - profiles.reported) / profiles.reported
    _grid = _error.unstack("month")
    _limit = float(np.nanmax(np.abs(_grid.values)))
    _figure,_axis = plt.subplots(figsize=(10,5.5),constrained_layout=True)
    _image = _axis.imshow(_grid.values,aspect="auto",origin="lower",cmap="RdBu_r",vmin=-_limit,vmax=_limit)
    _axis.set_xticks(range(_grid.shape[1]),_grid.columns)
    _axis.set_yticks(range(0,24,3),[f"{x:02d}:00" for x in range(0,24,3)])
    _axis.set_xlabel("Month (UTC)")
    _axis.set_ylabel("Hour of day (Pacific time)")
    _axis.set_title("Mean calibrated error (% of mean reported load)",loc="left")
    _figure.colorbar(_image,ax=_axis,label="Error (%)")
    _figure
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Calibration by month

    The weights selected by the predeclared rule in each month, the
    resulting CAISO and WECC net-load peaks against their ceilings, and the
    load-shape distortion the calibration introduced.
    """)
    return


@app.cell
def _(calibration, mo, pd):
    _summary = calibration["summary"]
    _regions = calibration["regions"]
    _blocks = pd.DatetimeIndex(_summary.index)
    def _value(name,block,column):
        try:
            return _regions.loc[(block,name),column]
        except KeyError:
            return float("nan")
    _rows = []
    for _block,_label in zip(_summary.index,_blocks):
        _row = _summary.loc[_block]
        _rows.append({
            "Month": f"{_label:%b %Y}",
            "Status": _row.get("status",""),
            "Selection": _row.get("selection",""),
            "Energy weight μ": f"{_row.get('energy_weight',float('nan')):,.0f}",
            "CAISO / WECC drive λ": f"{_row.get('lambda_caiso',float('nan')):g} / {_row.get('lambda_wecc',float('nan')):g}",
            "Shape RMSE": f"{100*_row.get('shape_relative_rmse',float('nan')):.2f}%",
            "Max state energy error": f"{100*_row.get('state_energy_max_abs_relative_error',float('nan')):.3f}%",
            "CAISO peak / ceiling": f"{_value('CAISO',_block,'shaped_MW'):,.0f} / {_value('CAISO',_block,'target_MW'):,.0f} MW",
            "WECC peak / ceiling": f"{_value('WECC',_block,'shaped_MW'):,.0f} / {_value('WECC',_block,'target_MW'):,.0f} MW",
            })
    mo.ui.table(_rows,selection=None,show_column_summaries=False,show_data_types=False,
        show_download=False,show_search=False,page_size=12)
    return


@app.cell(hide_code=True)
def _(mo, regions):
    _members = [x for x,y in regions["CAISO"].items() if y > 0]
    mo.md(f"""
    ## Caveats

    - The CAISO region is the county membership in
      `loads/_test/data/state_groups.csv` ({len(_members)} counties).
      County boundaries do not follow balancing authority boundaries. Los
      Angeles (0.66, excluding LADWP, Burbank and Glendale) and Riverside
      (0.87, excluding the IID Coachella Valley load) have fractional
      membership, and Sacramento (SMUD) and Stanislaus (TID, Modesto ID)
      are excluded. Other counties served partly by non-CAISO utilities
      (e.g., Placer, Shasta, Merced, San Joaquin) are wholly in the region,
      so the regional energy can differ from the CAISO footprint even when
      the state energy targets are met exactly.

    - The CAISO peak target in `loads/_test/data/peak_target.csv` is each
      UTC month's peak of the cleaned EIA-930 CAISO demand
      (`loads/_test/data/WECC_CAISO_hourly_load_2018-2022.csv`), and the
      calibration drives each month's CAISO net-load peak to that ceiling.
      EIA-930 and `loads/caiso/2020.csv` are different sources, so the
      ceiling can differ slightly from the reported peak shown here.

    - CAISO reports hour-ending values in Pacific prevailing time. They are
      assigned to UTC hour-beginning timestamps, which are the model's
      convention, and only the hours common to both years are compared.

    - DG is the fixed county rooftop PV of
      `loads/wecc/county_dg_scaled.csv.gz`, scaled by state and year to EIA's
      estimated small-scale solar generation (see
      `loads/wecc/county_dg_scale.py`); errors in its hourly shape or county
      distribution appear directly as net-load errors during daylight hours.
    """)
    return


if __name__ == "__main__":
    app.run()
