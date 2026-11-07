"""WECC county net load calibrated to EIA-930 balancing authority load

This [marimo](https://marimo.io/) notebook calibrates the hourly WECC county
net loads to the monthly minimum and maximum demand that each US WECC
balancing authority (BA) reported to EIA Form 930, using
`loads.calibrate.CalibratePeaks`, and combines the calibrated county net
loads into a single table for review.

- **County net load.** `elec_net_MW = elec_total_MW - |elec_dg_MW|`, from the
  gross county load in `loads/wecc/wecc_estimate.csv.gz` and the rooftop PV
  in `loads/wecc/county_dg.csv.gz`. The DG is taken as given: it is neither
  scaled (the EIA-scaled `county_dg_scaled.csv.gz` is not used) nor
  calibrated, and counties missing from the file have no DG. A BA's
  reported demand is net of behind-the-meter DG, so the net load is the
  calibration basis.
- **BA participation.** Each county's net load is split among the BAs that
  serve it with the factors in `loads/wecc/county_ba.csv`
  (`loads/wecc/county_ba.py`, fitted to EIA-861 2018 utility sales and
  service territories, with documented overrides in
  `loads/wecc/county_ba_overrides.csv`).
- **Targets.** `loads/_test/data/ba_minmax_target.csv`: the monthly maximum
  and minimum of each BA's cleaned EIA-930 hourly demand, by UTC month.
- **Calibration.** For the selected month, each BA's county shares are
  calibrated separately so that the `peak` percentile of the BA total equals
  the BA's reported maximum and the `trough` percentile equals its reported
  minimum. Each county's calibrated net load is the sum of its calibrated BA
  shares; shares in BAs without EIA-930 demand (e.g., `SWPP`) are left
  uncalibrated.

Pick the year and month, then WECC, a state, or a BA, and optionally one
county of that state or BA. The download buttons save the calibrated net
and gross (total) load of every WECC county for 2018-2022, and the gross
load aggregated onto the WECC240 load nodes.
"""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="WECC Calibration to EIA-930")


@app.cell
def _(mo):
    mo.md(f"""
    ## {__doc__}
    """)
    return


@app.cell
def _(mo, np, pathlib, pd):
    # load the county loads, DG, BA factors and targets
    _root = pathlib.Path(*pathlib.Path(__file__).parts[:-2])
    _files = {
        "gross": _root / "wecc" / "wecc_estimate.csv.gz",
        "dg": _root / "wecc" / "county_dg.csv.gz",
        "factors": _root / "wecc" / "county_ba.csv",
        "overrides": _root / "wecc" / "county_ba_overrides.csv",
        "nodes": _root / "wecc" / "node_estimate_cf.csv",
        "targets": _root / "_test" / "data" / "ba_minmax_target.csv",
        "reported": _root / "_test" / "data" / "WECC_CAISO_hourly_load_2018-2022.csv",
        }
    _missing = [str(x.relative_to(_root)) for x in _files.values() if not x.exists()]
    mo.stop(_missing,mo.md(f"**Missing input files:** {', '.join(_missing)}"))
    with mo.status.spinner("Loading WECC county loads and DG"):
        gross = pd.read_csv(_files["gross"],index_col=[0],parse_dates=[0])
        dg = pd.read_csv(_files["dg"],index_col=[0],parse_dates=[0])
        dg = dg.reindex(index=gross.index,columns=gross.columns).fillna(0.0)  # missing counties: no DG
        net = gross - np.abs(dg)
        factors = pd.read_csv(_files["factors"])
        overrides = pd.read_csv(_files["overrides"])
        node_cf = pd.read_csv(_files["nodes"]).pivot_table(index="county_st",columns="node",
            values="cf",aggfunc="sum",fill_value=0.0)
        targets = pd.read_csv(_files["targets"],parse_dates=["timestamp"])
        reported = pd.read_csv(_files["reported"])
        reported.index = pd.to_datetime(reported["utc_hour_ending"],utc=True) - pd.Timedelta(hours=1)
        reported = reported[["WECC_load_MW","CAISO_load_MW"]]
    bas = sorted(targets.ba.unique())
    states = sorted({x.rsplit(" ",1)[1] for x in net.columns})
    return bas, dg, factors, net, node_cf, overrides, reported, states, targets


@app.cell
def _(bas, mo, net, states):
    # time, percentile and region selection
    _years = sorted({str(x) for x in net.index.year.unique()})
    year_ui = mo.ui.dropdown(options=_years,value="2020",label="Year:")
    _months = {pd_month:f"{n:02d}" for n,pd_month in enumerate(
        ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],start=1)}
    month_ui = mo.ui.dropdown(options=_months,value="Aug",label="Month:")
    peak_ui = mo.ui.slider(start=0.90,stop=1.0,step=0.005,value=1.0,label="Peak percentile:",show_value=True)
    trough_ui = mo.ui.slider(start=0.0,stop=0.10,step=0.005,value=0.0,label="Trough percentile:",show_value=True)
    _regions = {"WECC":"WECC"}
    _regions.update({f"State: {x}":f"state:{x}" for x in states})
    _regions.update({f"BA: {x}":f"ba:{x}" for x in bas})
    region_ui = mo.ui.dropdown(options=_regions,value="WECC",label="Region:")
    return month_ui, peak_ui, region_ui, trough_ui, year_ui


@app.cell
def _(factors, mo, net, region_ui):
    # county selection within the state or BA
    _kind,_,_name = region_ui.value.partition(":")
    if _kind == "state":
        _counties = [x for x in net.columns if x.endswith(f" {_name}")]
    elif _kind == "ba":
        _counties = sorted(factors[factors.ba == _name].county_st)
    else:
        _counties = []
    _label = {"state":"entire state","ba":"entire BA"}.get(_kind,"all counties")
    county_ui = mo.ui.dropdown(options=[_label]+_counties,value=_label,label="County:")
    return (county_ui,)


@app.cell
def _(county_ui, mo, month_ui, peak_ui, region_ui, trough_ui, year_ui):
    _controls = [year_ui,month_ui,region_ui]
    if region_ui.value != "WECC":
        _controls.append(county_ui)
    mo.vstack([mo.hstack(_controls,justify="start"),mo.hstack([peak_ui,trough_ui],justify="start")])
    return


@app.cell
def _(CalibratePeaks, factors, net, pd, targets):
    def calibrate_month(start,peak,trough):
        """Calibrate each BA's county shares for the month starting at `start`

        Returns the uncalibrated county net load of the month, the
        uncalibrated and calibrated county shares by BA, and the BA
        calibration summary. Shares in BAs without EIA-930 targets are left
        as is.
        """
        _rows = (net.index >= start) & (net.index < start + pd.DateOffset(months=1))
        _month = net.loc[_rows]
        _targets = targets[targets.timestamp == start].set_index("ba")
        _shares,_calibrated,_records = {},{},[]
        for _ba,_group in factors.groupby("ba"):
            _weights = _group.set_index("county_st").factor
            _frame = _month[_weights.index] * _weights
            _shares[_ba] = _frame
            if _ba not in _targets.index or _month.empty:
                _calibrated[_ba] = _frame   # no EIA-930 demand: left as is
                continue
            _peaks = pd.DataFrame({"max":[_targets.loc[_ba,"max"]],"min":[_targets.loc[_ba,"min"]]},
                index=pd.DatetimeIndex([start],name="timestamp"))
            _result = CalibratePeaks(_frame.add_suffix("_MW"),_peaks,peak=peak,trough=trough)
            _calibrated[_ba] = pd.DataFrame(_result).rename(columns=lambda x:x[:-3])
            _total = _frame.sum(axis=1)
            _shaped = _calibrated[_ba].sum(axis=1)
            _parameters = _result.parameters.iloc[0]
            _records.append({
                "BA": _ba,
                "counties": len(_weights),
                "target max (MW)": _targets.loc[_ba,"max"],
                "target min (MW)": _targets.loc[_ba,"min"],
                "model max (MW)": _total.max(),
                "model min (MW)": _total.min(),
                "scale": _parameters.scale,
                "offset (MW)": _parameters.offset_MW,
                "calibrated max (MW)": _shaped.max(),
                "calibrated min (MW)": _shaped.min(),
                "model energy (GWh)": _total.sum() / 1000,
                "calibrated energy (GWh)": _shaped.sum() / 1000,
                "energy change (%)": 100 * (_shaped.sum() / _total.sum() - 1),
                "hours above max": int((_shaped > _targets.loc[_ba,"max"] + 1e-6).sum()),
                "hours below min": int((_shaped < _targets.loc[_ba,"min"] - 1e-6).sum()),
                })
        _summary = pd.DataFrame(_records).set_index("BA") if _records else pd.DataFrame()
        return _month,_shares,_calibrated,_summary

    def combine(calibrated,columns):
        """Sum the calibrated BA shares into one column per county"""
        return sum(x.reindex(columns=columns,fill_value=0.0) for x in calibrated.values())
    return calibrate_month, combine


@app.cell
def _(
    calibrate_month,
    combine,
    mo,
    month_ui,
    pd,
    peak_ui,
    targets,
    trough_ui,
    year_ui,
):
    # calibrate each BA's county shares for the selected month
    start = pd.Timestamp(f"{year_ui.value}-{month_ui.value}-01",tz="UTC")
    uncalibrated,shares,calibrated,ba_summary = calibrate_month(start,peak_ui.value,trough_ui.value)
    mo.stop(uncalibrated.empty or not (targets.timestamp == start).any(),
        mo.md(f"**No load or targets for {start:%Y-%m}.**"))

    # combine all WECC county net loads into one table
    combined = combine(calibrated,uncalibrated.columns).round(3)
    return ba_summary, calibrated, combined, shares, start, uncalibrated


@app.cell
def _(
    calibrate_month,
    combine,
    dg,
    gzip,
    io,
    mo,
    net,
    node_cf,
    np,
    pd,
    peak_ui,
    targets,
    trough_ui,
):
    # download the 2018-2022 calibration of all WECC counties
    _cache = {}
    _names = {"total":"county_total.csv.gz","net":"county_net.csv.gz","node":"node_total.csv.gz"}
    def _calibrate_all():
        _key = (peak_ui.value,trough_ui.value)
        if _key not in _cache:
            _months = []
            for _start in sorted(targets.timestamp.unique()):
                _month,_,_calibrated,_ = calibrate_month(pd.Timestamp(_start),*_key)
                if not _month.empty:
                    _months.append(combine(_calibrated,_month.columns))
            _net = pd.concat(_months).reindex(net.index)
            _total = _net + np.abs(dg)   # DG taken as given
            _net.index.name = _total.index.name = "timestamp"
            _node = _total[node_cf.index] @ node_cf   # county total load on WECC240 load nodes
            _node.index.name = "timestamp"
            _cache[_key] = {"net":_net.round(4),"total":_total.round(4),"node":_node.round(4)}
        return _cache[_key]
    def _csv_gz(kind):
        def _data():
            with mo.status.spinner(f"Calibrating 2018-2022 and writing {_names[kind]}"):
                _buffer = io.BytesIO()
                with gzip.GzipFile(fileobj=_buffer,mode="wb",mtime=0) as _fh:
                    _calibrate_all()[kind].to_csv(_fh,index=True,header=True)
                return _buffer.getvalue()
        return _data
    mo.vstack([
        mo.md(f"""### Download

    The calibration of every WECC county for every month of 2018-2022 with
    the percentiles above (peak {peak_ui.value}, trough {trough_ui.value}):
    calibrated net load `county_net.csv.gz`, and gross load
    `county_total.csv.gz` = net load + the given DG, in MW with one column per
    `"County ST"`, hour-beginning UTC. `node_total.csv.gz` is the county gross
    load allocated to the WECC240 load nodes (one column per node geohash)
    with the contribution factors in `loads/wecc/node_estimate_cf.csv`
    (in-county load busses by bus load, otherwise the nearest load node); it
    holds the US county load only, not the Canadian and Mexican nodes.
    Building the files takes a minute or two."""),
        mo.hstack([
            mo.download(data=_csv_gz(_kind),filename=_name,
                mimetype="application/gzip",label=_name)
            for _kind,_name in _names.items()
            ],justify="start"),
        ])
    return


@app.cell
def _(
    calibrated,
    combined,
    county_ui,
    net,
    pd,
    region_ui,
    reported,
    shares,
    start,
    targets,
    uncalibrated,
):
    # series and counties for the selected region and county
    _kind,_,_name = region_ui.value.partition(":")
    _county = county_ui.value if county_ui.value in net.columns else None
    target_lines = None
    reference = None
    if _kind == "ba":
        if _county:
            columns = [_county]
            before = shares[_name][_county]
            after = calibrated[_name][_county]
            title = f"{_county} share of {_name}"
        else:
            columns = list(shares[_name].columns)
            before = shares[_name].sum(axis=1)
            after = calibrated[_name].sum(axis=1)
            title = f"BA {_name}"
            _row = targets[(targets.timestamp == start) & (targets.ba == _name)]
            if not _row.empty:
                target_lines = (_row["min"].iloc[0],_row["max"].iloc[0])
            if _name == "CISO":
                reference = ("EIA-930 CISO demand",reported["CAISO_load_MW"])
    elif _kind == "state":
        columns = [_county] if _county else [x for x in net.columns if x.endswith(f" {_name}")]
        before = uncalibrated[columns].sum(axis=1)
        after = combined[columns].sum(axis=1)
        title = _county if _county else f"State {_name}"
    else:
        columns = list(net.columns)
        before = uncalibrated.sum(axis=1)
        after = combined.sum(axis=1)
        title = "WECC (US)"
        reference = ("EIA-930 WECC demand (US BAs)",reported["WECC_load_MW"])
    if reference is not None:
        reference = (reference[0],reference[1].reindex(after.index))
    series = pd.DataFrame({"model":before,"calibrated":after})
    return columns, reference, series, target_lines, title


@app.cell
def _(mo, plt, reference, series, start, target_lines, title):
    # hourly net load plot
    _fig,_ax = plt.subplots(figsize=(11,4))
    _ax.plot(series.index,series["model"],color="tab:gray",linewidth=0.8,label="model net load")
    _ax.plot(series.index,series["calibrated"],color="tab:blue",linewidth=1.0,label="calibrated net load")
    if reference is not None:
        _ax.plot(reference[1].index,reference[1],color="tab:orange",linewidth=0.8,label=reference[0])
    if target_lines is not None:
        for _value,_label in zip(target_lines,["EIA-930 monthly min","EIA-930 monthly max"]):
            _ax.axhline(_value,color="tab:red",linestyle="--",linewidth=0.8,label=_label)
    _ax.set_title(f"{title}, {start:%B %Y} (UTC)")
    _ax.set_ylabel("Net load (MW)")
    _ax.grid(alpha=0.3)
    _ax.legend(loc="upper left",fontsize=8,ncol=2)
    _fig.autofmt_xdate()
    _stats = series.agg(["max","min","mean"]).T
    _stats["energy (GWh)"] = series.sum() / 1000
    mo.vstack([_fig,mo.ui.table(_stats.round(1),selection=None)])
    return


@app.cell
def _(ba_summary, mo, region_ui):
    # BA calibration summary
    _kind,_,_name = region_ui.value.partition(":")
    _table = ba_summary.loc[[_name]] if _kind == "ba" and _name in ba_summary.index else ba_summary
    mo.vstack([
        mo.md("""### BA calibration

    `scale` and `offset` map the BA's model net load onto its EIA-930 monthly
    min/max. Scales far from one show where the county estimate or the BA
    factors disagree with the reported BA load."""),
        mo.ui.table(_table.round(3),selection=None,page_size=30),
        ])
    return


@app.cell
def _(columns, combined, factors, mo, overrides, pd, uncalibrated):
    # county summary and BA participation for the selection
    _factors = factors[factors.county_st.isin(columns)]
    _ba = _factors.groupby("county_st").apply(
        lambda x:", ".join(f"{b} {f:.2f}" for b,f in zip(x.ba,x.factor)),include_groups=False)
    _method = _factors.groupby("county_st").method.first()
    _summary = pd.DataFrame({
        "BA factors": _ba,
        "method": _method,
        "model energy (MWh)": uncalibrated[columns].sum(),
        "calibrated energy (MWh)": combined[columns].sum(),
        "calibrated max (MW)": combined[columns].max(),
        "calibrated min (MW)": combined[columns].min(),
        "model negative hours": (uncalibrated[columns] < 0).sum(),
        "calibrated negative hours": (combined[columns] < 0).sum(),
        })
    _summary["energy change (%)"] = 100 * (_summary["calibrated energy (MWh)"]
        / _summary["model energy (MWh)"] - 1)
    _overrides = overrides[overrides.county_st.isin(columns)]
    _items = [
        mo.md("### Counties"),
        mo.ui.table(_summary.round(3),selection=None,page_size=20),
        ]
    if not _overrides.empty:
        _items += [mo.md("#### BA factor overrides"),mo.ui.table(_overrides,selection=None)]
    mo.vstack(_items)
    return


@app.cell
def _(columns, combined, mo):
    # combined hourly county net loads
    mo.vstack([
        mo.md("""### Calibrated county net load (MW)

    All WECC county net loads after calibration, combined into one table
    (hour-beginning UTC), limited to the selected region or county."""),
        mo.ui.table(combined[columns],page_size=24,selection=None),
        ])
    return


@app.cell
def _():
    import marimo as mo
    import gzip
    import io
    import pathlib
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from loads.calibrate import CalibratePeaks

    return CalibratePeaks, gzip, io, mo, np, pathlib, pd, plt


if __name__ == "__main__":
    app.run()
