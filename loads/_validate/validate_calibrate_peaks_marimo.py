import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    This notebook validates the peak-calibrated load made by
    `loads/_review/review_wecc_calibrate_eia930_marimo.py` with
    `loads.calibrate.CalibratePeaks` against the hourly demand the US WECC
    balancing authorities (BAs) reported on EIA Form 930.

    - **WECC** (no BA selected): the calibrated total (gross) load of all WECC
      counties on the WECC240 load nodes, `loads/wecc/node_total.csv.gz`, and
      its net load, i.e., less the county rooftop PV in
      `loads/wecc/county_dg.csv.gz` allocated to the nodes with
      `loads/wecc/node_estimate_cf.csv`, against the reported WECC demand
      (`WECC_load_MW` in `loads/_test/data/WECC_CAISO_hourly_load_2018-2022.csv`).
    - **A BA**: the BA's calibrated net load, `loads/wecc/ba_net.csv.gz`, and its
      total load, i.e., plus its share of the county rooftop PV by the factors
      in `loads/wecc/county_ba.csv`, against the BA's reported demand
      (`loads/_test/data/WECC_BA_hourly_load_2018-2022.csv`).

    EIA-930 demand is net of rooftop PV, so the metrics compare the calibrated
    net load with the reported demand. Each BA is calibrated to its own
    reported monthly maximum and minimum, so the metrics measure the hourly
    shape within each month.
    """)
    return


@app.cell
def _(np, os, pd):
    _folder = os.path.dirname(os.path.dirname(__file__))
    node_total = pd.read_csv(os.path.join(_folder,"wecc","node_total.csv.gz"),index_col=[0],parse_dates=[0])

    # rooftop PV on the nodes, as used for node_total.csv.gz
    _cf = pd.read_csv(os.path.join(_folder,"wecc","node_estimate_cf.csv")).pivot_table(
        index="county_st",columns="node",values="cf",aggfunc="sum",fill_value=0.0)
    _dg = pd.read_csv(os.path.join(_folder,"wecc","county_dg.csv.gz"),index_col=[0],parse_dates=[0])
    _dg = np.abs(_dg.reindex(index=node_total.index,columns=_cf.index).fillna(0.0))
    node_dg = (_dg @ _cf).reindex(columns=node_total.columns,fill_value=0.0)
    node_net = node_total - node_dg

    # BA calibrated net load and rooftop PV share
    ba_net = pd.read_csv(os.path.join(_folder,"wecc","ba_net.csv.gz"),index_col=[0],parse_dates=[0])
    _ba_cf = pd.read_csv(os.path.join(_folder,"wecc","county_ba.csv")).pivot_table(
        index="county_st",columns="ba",values="factor",aggfunc="sum",fill_value=0.0)
    _dg = pd.read_csv(os.path.join(_folder,"wecc","county_dg.csv.gz"),index_col=[0],parse_dates=[0])
    _dg = np.abs(_dg.reindex(index=ba_net.index,columns=_ba_cf.index).fillna(0.0))
    ba_dg = (_dg @ _ba_cf).reindex(columns=ba_net.columns,fill_value=0.0)

    # EIA-930 reported demand, hour-ending UTC to hour-beginning UTC
    def _read(name):
        _data = pd.read_csv(os.path.join(_folder,"_test","data",name))
        _data.index = pd.to_datetime(_data.pop("utc_hour_ending"),utc=True) - pd.Timedelta(hours=1)
        return _data.drop(columns="pst_hour_ending",errors="ignore")
    reported = _read("WECC_CAISO_hourly_load_2018-2022.csv")["WECC_load_MW"].reindex(node_total.index)
    ba_reported = _read("WECC_BA_hourly_load_2018-2022.csv").reindex(index=ba_net.index)
    return ba_dg, ba_net, ba_reported, node_dg, node_net, node_total, reported


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
def _(ba_net, mo):
    ba_ui = mo.ui.dropdown(options=list(ba_net.columns),label="BA:")
    return (ba_ui,)


@app.cell
def _(ba_ui, mo, month_ui, year_ui):
    mo.hstack([year_ui,month_ui,ba_ui],justify="start")
    return


@app.cell
def _(ba_ui):
    plot_options = dict(
        figsize=(10, 8),
        grid=True,
        title="WECC" if ba_ui.value is None else ba_ui.value,
        xlabel="Date/Time (UTC)",
        ylabel="Load (GW)",
    )
    return (plot_options,)


@app.cell
def _(
    ba_dg,
    ba_net,
    ba_reported,
    ba_ui,
    month_ui,
    node_dg,
    node_net,
    node_total,
    pd,
    reported,
    year_ui,
):
    # selected series
    if ba_ui.value is None:
        data = pd.DataFrame({
            "Calibrated total": node_total.sum(axis=1),
            "Calibrated net": node_net.sum(axis=1),
            "EIA-930 reported": reported,
            })
        rooftop = node_dg.sum(axis=1)
    else:
        data = pd.DataFrame({
            "Calibrated total": ba_net[ba_ui.value] + ba_dg[ba_ui.value],
            "Calibrated net": ba_net[ba_ui.value],
            "EIA-930 reported": ba_reported[ba_ui.value],
            })
        rooftop = ba_dg[ba_ui.value]
    if not year_ui.value is None:
        data = data.loc[data.index.year==year_ui.value]
        if not month_ui.value is None:
            data = data.loc[data.index.month==month_ui.value]
    rooftop = rooftop.loc[data.index]
    return data, rooftop


@app.cell
def _(data, mo, plot_options):
    mo.mpl.interactive((data/1000).plot(**plot_options))
    return


@app.cell
def _(data, mo, np, pd, rooftop):
    # validation metrics: calibrated net load vs EIA-930 reported demand
    _pair = data[["Calibrated net","EIA-930 reported"]].dropna()
    _model,_actual = _pair["Calibrated net"],_pair["EIA-930 reported"]
    _error = _model - _actual
    _metrics = {
        "MAPE (%)": 100 * float(np.mean(np.abs(_error) / _actual)),
        "MAE (MW)": float(np.mean(np.abs(_error))),
        "RMSE (MW)": float(np.sqrt(np.mean(np.square(_error)))),
        "R²": 1 - float(np.sum(np.square(_error)) / np.sum(np.square(_actual - _actual.mean()))),
        "Energy error (%)": 100 * float(_error.sum() / _actual.sum()),
        }
    _table = pd.DataFrame({
        "Hours": [len(_pair)],
        "Reported energy (GWh)": [_actual.sum() / 1e3],
        "Calibrated net energy (GWh)": [_model.sum() / 1e3],
        "Energy error (GWh)": [_error.sum() / 1e3],
        "Reported peak (MW)": [_actual.max()],
        "Calibrated net peak (MW)": [_model.max()],
        "Rooftop PV energy (GWh)": [rooftop.loc[_pair.index].sum() / 1e3],
        })
    _output = mo.vstack([
        mo.hstack([
            mo.stat(f"{_metrics['MAPE (%)']:.2f}%",label="MAPE",bordered=True),
            mo.stat(f"{_metrics['MAE (MW)']:,.0f} MW",label="MAE",bordered=True),
            mo.stat(f"{_metrics['RMSE (MW)']:,.0f} MW",label="RMSE",bordered=True),
            mo.stat(f"{_metrics['R²']:.4f}",label="R²",bordered=True),
            mo.stat(f"{_metrics['Energy error (%)']:+.2f}%",label="Total energy error",bordered=True),
            ],justify="start"),
        mo.ui.table(_table.round(1),selection=None),
        mo.md("Calibrated net load vs EIA-930 reported demand, over the hours shown above that have reported data."),
        ])
    _output
    return


@app.cell
def _():
    import marimo as mo
    import numpy as np
    import pandas as pd
    import os
    import calendar

    return calendar, mo, np, os, pd


if __name__ == "__main__":
    app.run()
