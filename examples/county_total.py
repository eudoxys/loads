import marimo

__generated_with = "0.23.6"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    This notebook generates the county_total.csv file as follows:
    """)
    return


@app.cell
def _(mo):
    mo.mermaid("""
    flowchart LR
    
        county_cf.csv --> cf
        eia.HS861m --> state_mwh
        loads.Total -->|Σ
    months| model_mwh
        loads.Total --> mw

        cf --> mul1
        state_mwh --> mul1
        mw --> mul1
        model_mwh -->|1/| mul1
        mul1((x)) --> load --> county_totals.csv
    """)
    return


@app.cell
def _(Total, pd):
    # Setup and configuration
    start = "2018-01-01 00:00:00+0000"
    stop = "2022-12-31 23:59:59+0000"
    refresh = False # flag to induce full refresh of cache
    # pd.options.display.max_rows = None 
    pd.options.display.max_columns = None
    pd.options.display.width = None

    Total.cache = None # disables estimator caching (saves memory)

    date_range = pd.date_range(start,stop,freq="1h")
    return date_range, refresh, start, stop


@app.cell
def _(Counties, mo):
    # Step 1: get the counties for which data needs to be collected
    with mo.status.spinner("Loading counties"):
        wecc_counties = Counties(use_index=["RO"],selection="WECC",set_index=["ST","COUNTY"])
    return (wecc_counties,)


@app.cell
def _(mo, pd):
    # Step 2: get DG data
    with mo.status.spinner("Loading county DG"):
        wecc_dg = pd.read_csv("county_dg.csv.gz",index_col=[0],parse_dates=[0])
    return (wecc_dg,)


@app.cell
def _(mo, pd):
    # Step 3: get county energy contribution factors to state energy
    with mo.status.spinner("Loading county CF"):
        wecc_cf = pd.read_csv("county_cf.csv",index_col=[0])
        wecc_cf.index = pd.DatetimeIndex(wecc_cf.index,tz="UTC")
        wecc_cf.index.name="timestamp"
    return (wecc_cf,)


@app.cell
def _(HS861m, date_range, dt, mo, pd, wecc_counties):
    # Step 4: get state energy consumption
    _dates = pd.date_range(date_range[0],date_range[-1]+dt.timedelta(hours=1),freq="MS")
    with mo.status.progress_bar(title="Loading state energy demand",total=len(_dates),remove_on_exit=True) as _bar:
        wecc_mwh = []
        states = wecc_counties.index.get_level_values(0).unique().tolist()
        for _dt in _dates:
            _bar.update(subtitle=str(_dt))
            _mwh = HS861m(_dt.year,_dt.month)
            wecc_mwh.append(_mwh.loc[states,"tot_energy_mwh"].to_frame(_dt).T)
        wecc_mwh = pd.concat(wecc_mwh)

    return (wecc_mwh,)


@app.cell
def _(
    Cache,
    Total,
    date_range,
    mo,
    pd,
    refresh,
    start,
    stop,
    wecc_cf,
    wecc_counties,
    wecc_dg,
    wecc_mwh,
):
    # Step 5: get total loads with the DG data
    totals = []
    with mo.status.progress_bar(title="Processing county loads...",total=len(wecc_counties),remove_on_exit=True) as _bar:
        for _state,_county in wecc_counties.index:
            _county_st = f"{_county} {_state}"
            _bar.update(subtitle=_county_st)
            messages = []
    
            cache = Cache(package="loads",version=0,path=[_state,_county,f"Total_{start[:4]}-{stop[:4]}.csv"])
            if cache.exists() and not refresh:
                load = pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0])
            else:
                try:
                    load = Total(_state,_county,date_range=date_range,refresh=refresh,samples=0).round(3)
                    load.to_csv(cache.pathname,index=True)
                except Exception as err:
                    messages.append(str(err))
    
    
            # get county DG
            if _county_st in wecc_dg.columns:
                dg = wecc_dg[_county_st]
                load["elec_dg_MW"] = dg
            else:
                messages.append("no DG data")
                load["elec_dg_MW"] = 0.0
                dg = load["elec_dg_MW"]
    
            # get state-level energy total
            _mwh = wecc_mwh[_state].resample("1h").ffill()
            load["state_mwh"] = _mwh
    
            # get county contribution factor to state-level energy total
            if _county_st in wecc_cf.columns:
                cf = wecc_cf[_county_st].resample("1h").ffill()
                load["county_cf"] = cf
    
                # get original county-level energy total
                old_mwh = load["elec_total_MW"].resample("MS").sum().resample("1h").ffill()
                load["old_mwh"] = old_mwh
    
                # calculate actual county-level energy total
                new_mwh = _mwh * cf + dg.resample("MS").sum().resample("1h").ffill()
                load["new_mwh"] = new_mwh
            
                # calculate new MW
                load["new_MW"] = load["elec_total_MW"] * new_mwh / old_mwh
    
                totals.append(load["new_MW"].to_frame(_county_st).round(3))
    
            else:
                messages.append("no CF data")
            if messages:
                print("ERROR:",_county_st,", ".join(messages))

    return load, totals


@app.cell
def _(load, mo):
    mo.ui.table(load,page_size=24)
    return


@app.cell
def _(pd, totals):
    result = pd.concat(totals,axis=1)
    result.index.name = "timestamp"
    result.to_csv("county_totals.csv.gz",index=True,compression="gzip")
    return


@app.cell
def _():
    import marimo as mo
    import os
    import datetime as dt
    import pandas as pd

    from fips import Counties
    from loads.total import Total
    from eia import HS861m
    from cache import Cache

    return Cache, Counties, HS861m, Total, dt, mo, pd


if __name__ == "__main__":
    app.run()
