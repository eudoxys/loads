"""Explore the sensitivity of the August 2020 WECC calibration

Run with

    marimo edit loads/_explore/explore_calibrate_marimo.py

The notebook uses the same inputs as `loads/_test/test_calibrate.py`: the
assembled August 2020 county load matrix from the local cache, DG from
`loads/wecc/county_dg_scaled.csv.gz`, and the targets and CAISO/WECC membership in
`loads/_test/data`. Build the load matrix first with

    python loads/_test/test_calibrate.py
"""

import marimo

__generated_with = "0.25.1"
app = marimo.App(width="full")


@app.cell
def _():
    import os
    from contextlib import ExitStack
    from pathlib import Path

    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from matplotlib.colors import LogNorm

    from cache import Cache
    from loads.calibrate import Calibrate

    return Cache, Calibrate, ExitStack, LogNorm, Path, mo, np, os, pd, plt


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Calibration sensitivity

    **August 2020 net-load shaping over all WECC counties**

    Explore the global trade-off across the predeclared weight grid, inspect a
    chosen operating point, and use its dual variables to probe local
    sensitivity to the regional peak ceilings. See `loads.calibrate` for the
    formulation.
    """)
    return


@app.cell
def _(Cache, Path, os, pd):
    MONTH = "2020-08"
    START = pd.Timestamp(f"{MONTH}-01 00:00:00+00:00")
    PACKAGE = Path(__file__).resolve().parents[1]
    DATA = PACKAGE / "_test" / "data"
    if os.environ.get("LOADS_CACHEDIR"):
        Cache.CACHEDIR = os.environ["LOADS_CACHEDIR"]
    load_cache = Cache(package="loads",version=0,path=["_test",f"calibrate_X_{MONTH}.csv.gz"])
    sweep_cache = Cache(package="loads",version=0,path=["_explore",f"calibrate_sweep_{MONTH}.csv.gz"])
    report_sweep = PACKAGE / "tests" / "calibrate" / f"sweep_{MONTH}.csv"
    return DATA, MONTH, PACKAGE, START, load_cache, report_sweep, sweep_cache


@app.cell
def _(DATA, PACKAGE, START, load_cache, mo, pd):
    mo.stop(not load_cache.exists(),mo.callout(mo.md(
        "The August 2020 load matrix is not in the cache. Build it with "
        "`python loads/_test/test_calibrate.py` (or run the calibration test) "
        "and rerun this notebook."),kind="warn"))

    def _month_row(name):
        _data = pd.read_csv(DATA / name,index_col=[0])
        _data.index = pd.to_datetime(_data.index,utc=True)
        return _data.loc[_data.index == START].iloc[0].dropna()

    load = pd.read_csv(load_cache.pathname,index_col=[0],parse_dates=[0])
    dg = pd.read_csv(PACKAGE / "wecc" / "county_dg_scaled.csv.gz",index_col=[0],parse_dates=[0])
    dg.index = pd.DatetimeIndex(dg.index).tz_convert("UTC")
    dg = dg.reindex(index=load.index,columns=load.columns).fillna(0.0).abs()
    energy = _month_row("energy_target.csv")
    peak = _month_row("peak_target.csv")[["CAISO","WECC"]]
    regions = pd.read_csv(DATA / "state_groups.csv",index_col=[0]).reindex(load.columns)
    return dg, energy, load, peak, regions


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Weight search

    The landscape below comes from the predeclared 88-point grid. A saved
    sweep is reused when one exists (from this notebook or from the
    calibration test report); otherwise run the search, which takes several
    minutes.
    """)
    return


@app.cell
def _(mo):
    search_button = mo.ui.run_button(label="Run weight search")
    search_button
    return (search_button,)


@app.cell
def _(Calibrate, ExitStack, dg, energy, load, mo, peak, pd, regions, report_sweep, search_button, sweep_cache):
    if search_button.value:
        with ExitStack() as _stack:
            _bar = {}
            def _progress(done,total,info):
                # open the bar on the first solve, once the total is known
                if not _bar:
                    _bar["bar"] = _stack.enter_context(mo.status.progress_bar(
                        total=total,title="Weight search",
                        completion_title="Weight search complete"))
                if info["step"] == "candidate":
                    _subtitle = (f"Candidate {info['candidate']} of {info['candidates']}: "
                        f"μ={info['energy_weight']:g}, "
                        f"λ={info.get('lambda_caiso',0):g}/{info.get('lambda_wecc',0):g} "
                        f"({info['status']})")
                else:
                    _subtitle = "Polishing the selected solution"
                _bar["bar"].update(subtitle=_subtitle)
            _result = Calibrate(load,dg=dg,energy=energy,peak=peak,regions=regions,
                search=True,progress=_progress)
        sweep = _result.sweep.copy()
        sweep.to_csv(sweep_cache.pathname,index=False,compression="gzip")
    elif sweep_cache.exists():
        sweep = pd.read_csv(sweep_cache.pathname)
    elif report_sweep.exists():
        sweep = pd.read_csv(report_sweep)
    else:
        sweep = None
    mo.stop(sweep is None,mo.callout(mo.md(
        "No saved weight sweep. Press **Run weight search**."),kind="neutral"))

    sweep = sweep[sweep.status.isin(["optimal","optimal_inaccurate"])].copy()
    sweep["shape_rmse_pct"] = 100 * sweep.shape_relative_rmse
    sweep["energy_rms_pct"] = 100 * sweep.state_energy_rms_relative_error
    sweep["energy_max_pct"] = 100 * sweep.state_energy_max_abs_relative_error
    sweep["caiso_peak_pct"] = 100 * sweep.caiso_peak_mw / peak["CAISO"]
    sweep["wecc_peak_pct"] = 100 * sweep.wecc_peak_mw / peak["WECC"]
    sweep["peak_deviation_pct"] = (sweep[["caiso_peak_pct","wecc_peak_pct"]] - 100).abs().max(axis=1)
    return (sweep,)


@app.cell
def _(Calibrate, sweep):
    # apply the predeclared selection rule to the saved sweep
    _qualifying = sweep[
        (sweep[["caiso_peak_shortfall_fraction","wecc_peak_shortfall_fraction"]].max(axis=1) <= Calibrate.PEAK_SHORTFALL_TOL)
        & (sweep.state_energy_max_abs_relative_error <= Calibrate.STATE_ENERGY_TOL)
        & (sweep.minimum_load_mw >= Calibrate.NONNEGATIVE_TOL)
        ].assign(drive_total=lambda x:x.lambda_caiso + x.lambda_wecc)
    rule_row = _qualifying.sort_values(["shape_relative_rmse","state_energy_rms_relative_error",
        "energy_weight","drive_total"]).iloc[0] if len(_qualifying) else None
    qualifying_count = len(_qualifying)
    return qualifying_count, rule_row


@app.cell
def _(mo, rule_row, sweep):
    _mu = sorted(sweep.energy_weight.unique())
    energy_ui = mo.ui.dropdown(
        options={f"{x:,.0f}":float(x) for x in _mu},
        value=f"{rule_row.energy_weight:,.0f}" if rule_row is not None else f"{_mu[0]:,.0f}",
        label="State-energy weight μ",
        full_width=True,
        )
    _pairs = sweep[sweep.energy_weight == _mu[0]][["lambda_caiso","lambda_wecc"]].drop_duplicates().values
    drive_ui = mo.ui.dropdown(
        options={f"{c:g} / {w:g}":f"{c:.8g}|{w:.8g}" for c,w in _pairs},
        value=f"{rule_row.lambda_caiso:g} / {rule_row.lambda_wecc:g}" if rule_row is not None else None,
        label="CAISO / WECC drive weights λ",
        full_width=True,
        )
    mo.hstack([energy_ui,drive_ui],widths="equal",gap=1.0)
    return drive_ui, energy_ui


@app.cell
def _(drive_ui, energy_ui, mo, np, sweep):
    mo.stop(drive_ui.value is None,mo.md("Choose the drive weights."))
    lambda_caiso,lambda_wecc = (float(x) for x in drive_ui.value.split("|"))
    selected_row = sweep[(sweep.energy_weight == energy_ui.value)
        & np.isclose(sweep.lambda_caiso,lambda_caiso)
        & np.isclose(sweep.lambda_wecc,lambda_wecc)].iloc[0]
    return lambda_caiso, lambda_wecc, selected_row


@app.cell
def _(load, mo, qualifying_count, rule_row, selected_row, sweep):
    _rule = (f"Selection rule picks candidate {int(rule_row.candidate)} "
        f"({qualifying_count} of {len(sweep)} pass the tolerances)"
        if rule_row is not None else "No candidate passes the selection tolerances")
    mo.vstack([
        mo.hstack([
            mo.stat(f"{selected_row.shape_rmse_pct:.2f}%",
                label="Signal deformation",caption="Load-shape relative RMSE",bordered=True),
            mo.stat(f"{selected_row.energy_rms_pct:.4f}%",
                label="State-energy RMS error",caption=f"Maximum {selected_row.energy_max_pct:.4f}%",bordered=True),
            mo.stat(f"{selected_row.caiso_peak_pct:.1f}% / {selected_row.wecc_peak_pct:.1f}%",
                label="Regional peak attainment",
                caption=f"CAISO / WECC · worst deviation {selected_row.peak_deviation_pct:.3f}%",bordered=True),
            mo.stat(f"{int(selected_row.output_peak_caps_active)} / {int(selected_row.column_rmse_caps_active)}",
                label="Unit safeguards active",caption=f"Peak cap / RMS cap, of {load.shape[1]}",bordered=True),
            ],widths="equal",gap=0.75),
        mo.md(f"Candidate **{int(selected_row.candidate)}** · {_rule}"),
        ],gap=0.5)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Global preference landscape

    Each point is one solved weight combination. Panels separate the
    state-energy weights, the vertical axis shows the worst CAISO/WECC
    peak-target deviation, and color shows state-energy RMS error on a
    logarithmic scale. The star marks the chosen point and the open circle the
    candidate picked by the selection rule.
    """)
    return


@app.cell
def _(LogNorm, plt, rule_row, selected_row, sweep):
    _mu = sorted(sweep.energy_weight.unique())
    _rows = int((len(_mu) + 1) // 2)
    _figure,_axes = plt.subplots(_rows,2,figsize=(11.5,4.0*_rows),sharex=True,sharey=True,
        constrained_layout=True,squeeze=False)
    _top = sweep.peak_deviation_pct.max()
    _norm = LogNorm(vmin=max(sweep.energy_rms_pct.min(),1e-6),vmax=sweep.energy_rms_pct.max())
    _points = None
    for _axis,_value in zip(_axes.flat,_mu):
        _group = sweep[sweep.energy_weight == _value]
        _points = _axis.scatter(_group.shape_rmse_pct,_group.peak_deviation_pct,c=_group.energy_rms_pct,
            cmap="viridis",norm=_norm,s=46,alpha=0.85,edgecolors="#374151",linewidths=0.35)
        if selected_row.energy_weight == _value:
            _axis.scatter([selected_row.shape_rmse_pct],[selected_row.peak_deviation_pct],
                c=[selected_row.energy_rms_pct],cmap="viridis",norm=_norm,marker="*",s=260,
                edgecolor="black",linewidth=1.0,zorder=5,label=f"Candidate {int(selected_row.candidate)}")
        if rule_row is not None and rule_row.energy_weight == _value:
            _axis.scatter([rule_row.shape_rmse_pct],[rule_row.peak_deviation_pct],marker="o",s=180,
                facecolors="none",edgecolors="tab:red",linewidths=1.5,zorder=6,label="Selection rule")
        _axis.set_title(f"State-energy weight μ = {_value:,.0f}")
        _axis.grid(True,linewidth=0.5,alpha=0.3)
        _axis.set_xlim(left=0.0)
        _axis.set_ylim(bottom=-0.035*_top,top=1.05*_top)
        if _axis.get_legend_handles_labels()[0]:
            _axis.legend(loc="best")
    for _axis in list(_axes.flat)[len(_mu):]:
        _axis.set_visible(False)
    _figure.supxlabel("Signal deformation: load-shape relative RMSE (%)")
    _figure.supylabel("Worst CAISO/WECC peak-target deviation (%)")
    _figure.colorbar(_points,ax=_axes,label="State-energy RMS error (%), log scale",shrink=0.92)
    _figure
    return


@app.cell
def _(mo, selected_row):
    mo.ui.table([{
        "Candidate": int(selected_row.candidate),
        "Energy weight μ": f"{selected_row.energy_weight:,.0f}",
        "CAISO drive": f"{selected_row.lambda_caiso:g}",
        "WECC drive": f"{selected_row.lambda_wecc:g}",
        "Maximum state error": f"{selected_row.energy_max_pct:.5f}%",
        "State-energy RMS error": f"{selected_row.energy_rms_pct:.5f}%",
        "Worst peak deviation": f"{selected_row.peak_deviation_pct:.5f}%",
        "CAISO peak": f"{selected_row.caiso_peak_pct:.3f}%",
        "WECC peak": f"{selected_row.wecc_peak_pct:.3f}%",
        "Minimum load": f"{selected_row.minimum_load_mw:,.3f} MW",
        }],selection=None,show_column_summaries=False,show_data_types=False,
        show_download=False,show_search=False)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Local constraint sensitivity

    Re-solve the chosen point with fixed weights to obtain its active set and
    dual variables. The probe uses the summed peak-ceiling dual as the tangent
    to the optimal-value function; a change large enough to alter the active
    set needs another solve.
    """)
    return


@app.cell
def _(mo):
    resolve_button = mo.ui.run_button(label="Re-solve chosen point")
    target_ui = mo.ui.dropdown(options={"WECC ceiling":"WECC","CAISO ceiling":"CAISO"},
        value="WECC ceiling",label="Ceiling to perturb",full_width=True)
    change_ui = mo.ui.slider(start=-2.0,stop=2.0,step=0.1,value=-1.0,
        label="Peak-ceiling change (%)",show_value=True,full_width=True)
    mo.hstack([resolve_button,target_ui,change_ui],widths=[0.8,1.0,1.5],align="end",gap=1.0)
    return change_ui, resolve_button, target_ui


@app.cell
def _(Calibrate, dg, energy, load, mo, peak, regions):
    @mo.cache
    def solve_point(mu,lambda_caiso,lambda_wecc):
        """Calibrate with fixed weights"""
        return Calibrate(load,dg=dg,energy=energy,peak=peak,regions=regions,
            energy_weight=mu,drive={"CAISO":lambda_caiso,"WECC":lambda_wecc})
    return (solve_point,)


@app.cell
def _(lambda_caiso, lambda_wecc, mo, resolve_button, selected_row, solve_point):
    mo.stop(not (mo.app_meta().mode == "script" or resolve_button.value),mo.callout(
        mo.md("Press **Re-solve chosen point** to calculate its active set and duals."),kind="neutral"))
    with mo.status.spinner(title="Solving..."):
        point = solve_point(float(selected_row.energy_weight),lambda_caiso,lambda_wecc)
    _summary = point.summary.iloc[0]
    mo.md(f"**{_summary.status}** · CLARABEL solve {_summary.solve_seconds:.1f} s")
    return (point,)


@app.cell
def _(mo, point):
    mo.ui.table([{
        "Constraint family": name,
        "Active": f"{int(row.active)} / {int(row.total)}",
        "Maximum dual": f"{row.dual_max:.6g}",
        "Sum of duals": f"{row.dual_sum:.6g}",
        } for name,row in point.constraints.droplevel(0).iterrows()],
        selection=None,show_column_summaries=False,show_data_types=False,
        show_download=False,show_search=False)
    return


@app.cell
def _(change_ui, mo, peak, point, target_ui):
    _family = f"{target_ui.value} ceiling"
    _dual = point.constraints.droplevel(0).loc[_family,"dual_sum"]
    _normalized = peak[target_ui.value] / point.summary.iloc[0].normalization_MW
    _change = -_dual * _normalized * change_ui.value / 100.0
    _direction = "tightening" if change_ui.value < 0 else "loosening" if change_ui.value > 0 else "no change"
    mo.hstack([
        mo.stat(f"{_dual:.6g}",label="Summed dual",caption=_family,bordered=True),
        mo.stat(f"{_change:+.6g}",label="Predicted Δ objective",
            caption=f"First-order effect of {abs(change_ui.value):.1f}% {_direction}",bordered=True),
        ],widths="equal",gap=0.75)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Regional profiles

    Input and shaped net-load profiles of the chosen point against the peak
    ceilings.
    """)
    return


@app.cell
def _(dg, load, peak, plt, point, regions):
    _figure,_axes = plt.subplots(2,1,figsize=(13,7),sharex=True,constrained_layout=True)
    for _axis,_region in zip(_axes,["CAISO","WECC"]):
        _axis.plot(load.index,(load - dg) @ regions[_region],linewidth=1.0,label="Input")
        _axis.plot(point.index,point.net @ regions[_region],linewidth=1.0,label="Shaped")
        _axis.axhline(peak[_region],color="black",linestyle="--",linewidth=0.9,label="Peak ceiling")
        _axis.set_title(f"{_region} net load")
        _axis.set_ylabel("MW")
        _axis.legend(ncols=3,loc="upper left")
    _axes[-1].set_xlabel("August 2020 (UTC)")
    _figure
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Where the adjustment is carried

    Counties ranked by the RMS change of their shaped load, which shows which
    local signals absorb the regional correction.
    """)
    return


@app.cell
def _(load, mo, np, pd, point):
    _change = point - load
    _sse = np.square(_change).sum()
    _parameters = point.parameters.droplevel(0)
    burden = pd.DataFrame({
        "change_rmse_MW": np.sqrt(np.square(_change).mean()),
        "relative_rmse_pct": 100 * _parameters.relative_rmse,
        "sse_share_pct": 100 * _sse / _sse.sum(),
        "scale": _parameters.scale,
        "offset_MW": _parameters.offset_MW,
        "input_peak_MW": load.max(),
        "shaped_peak_MW": point.max(),
        }).sort_values("change_rmse_MW",ascending=False)
    top_ui = mo.ui.slider(start=5,stop=50,step=5,value=10,label="Counties shown",show_value=True)
    top_ui
    return burden, top_ui


@app.cell
def _(burden, mo, top_ui):
    mo.ui.table([{
        "County": county,
        "Change RMSE": f"{row.change_rmse_MW:,.1f} MW",
        "Relative RMSE": f"{row.relative_rmse_pct:.2f}%",
        "Share of shape SSE": f"{row.sse_share_pct:.2f}%",
        "Scale": f"{row.scale:.3f}",
        "Offset": f"{row.offset_MW:,.1f} MW",
        "Input peak": f"{row.input_peak_MW:,.1f} MW",
        "Shaped peak": f"{row.shaped_peak_MW:,.1f} MW",
        } for county,row in burden.head(top_ui.value).iterrows()],
        selection=None,show_column_summaries=False,show_data_types=False,
        show_download=False,show_search=False)
    return


@app.cell
def _(burden, mo):
    county_ui = mo.ui.dropdown(options=list(burden.index),value=burden.index[0],
        label="County",searchable=True)
    county_ui
    return (county_ui,)


@app.cell
def _(burden, county_ui, load, plt, point):
    _row = burden.loc[county_ui.value]
    _figure,_axis = plt.subplots(figsize=(13,3.5),constrained_layout=True)
    _axis.plot(load.index,load[county_ui.value],linewidth=1.0,label="Input")
    _axis.plot(point.index,point[county_ui.value],linewidth=1.0,label="Shaped")
    _axis.set_title(f"{county_ui.value} · scale {_row.scale:.3f}, offset {_row.offset_MW:,.1f} MW, "
        f"relative RMSE {_row.relative_rmse_pct:.1f}%",loc="left")
    _axis.set_ylabel("Load (MW)")
    _axis.legend(loc="upper left")
    _figure
    return


if __name__ == "__main__":
    app.run()
