"""WECC240 node load estimate

This [marimo](https://marimo.io/) notebook reviews the aggregation of the
uncalibrated county load estimates onto the WECC240 load nodes performed by
`loads/wecc/node_estimate.py`, using `loads/wecc/node_estimate.csv.gz` and the
county-to-node contribution factors in `loads/wecc/node_estimate_cf.csv`.
State borders are downloaded once into the `loads` cache.

Counties that contain WECC240 load busses are split among those busses' nodes
in proportion to the bus loads (`bus`). All other counties are assigned to
their nearest load node from `wecc240` `county_node_map.csv` (`nearest`).
The loads of the Canadian and Mexican nodes (`foreign`) are taken from the
`wecc240` node load files.
"""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="WECC240 Node Load Estimate")


@app.cell
def _(mo):
    mo.md(f"""
    ## {__doc__}
    """)
    return


@app.cell
def _(importlib, mo, pathlib, pd):
    # load the node estimate and contribution factors
    _folder = pathlib.Path(*pathlib.Path(__file__).parts[:-2],"wecc")
    _file = _folder / "node_estimate.csv.gz"
    mo.stop(not _file.exists(),
        mo.md(f"**{_file.name}** not found. Run `python3 node_estimate.py` in `loads/wecc` first."))
    with mo.status.spinner("Loading node estimate"):
        data = pd.read_csv(_file,index_col=[0],parse_dates=[0])
        cf = pd.read_csv(_folder / "node_estimate_cf.csv")
    _spec = importlib.util.spec_from_file_location("node_estimate",_folder / "node_estimate.py")
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    foreign = _module.FOREIGN
    return cf, data, foreign


@app.cell
def _(mo, pathlib, pd):
    # load the wecc240 reference data
    _local = pathlib.Path(*pathlib.Path(__file__).parts[:-3]).parent / "wecc240" / "wecc240" / "data"
    _url = "https://raw.githubusercontent.com/eudoxys/wecc240/main/wecc240/data"
    def _wecc240(name):
        return _local / name if _local.exists() else f"{_url}/{name}"
    with mo.status.spinner("Loading wecc240 data"):
        node_map = pd.read_csv(_wecc240("county_node_map.csv"),index_col="county_st")["load"]
        counties = pd.read_csv(_wecc240("counties.csv"),index_col="COUNTY_ST")[["LAT","LON"]]
        bus = pd.read_csv(_wecc240("bus_gis.csv"))
    nodes = bus.groupby("GEOHASH").agg(LAT=("LAT","first"),LON=("LON","first"),
        NAME=("NAME","first"),BUS_LOAD=("LOAD","sum"),BUSSES=("BUS_I","count"))
    return counties, node_map, nodes


@app.cell
def _(Cache, json, mo, urllib):
    # load the US state borders (downloaded once to the loads cache)
    _url = "https://raw.githubusercontent.com/python-visualization/folium/main/examples/data/us-states.json"
    _cache = Cache(package="loads",version=0,path=["us-states.json"])
    try:
        if not _cache.exists():
            with mo.status.spinner("Downloading state borders"):
                with urllib.request.urlopen(_url,timeout=30) as _response:
                    _text = _response.read().decode("utf-8")
            with open(_cache.pathname,"w",encoding="utf-8") as _fh:
                _fh.write(_text)
        with open(_cache.pathname,"r",encoding="utf-8") as _fh:
            states = json.load(_fh)["features"]
    except Exception: # pylint: disable=broad-exception-caught
        states = [] # map is drawn without state borders
    return (states,)


@app.cell
def _(cf, data, foreign, mo, node_map):
    # summary
    _total = data.sum(axis=1)
    _energy = (_total.resample("YS").sum()/1e6).round(1)
    _split = cf[cf.method=="bus"].groupby("county_st").node.count()
    _nearest = cf.groupby("county_st").apply(
        lambda x: x.loc[x.cf.idxmax(),"node"],include_groups=False)
    _changed = (_nearest != node_map.reindex(_nearest.index)).sum()
    _new = sorted(set(data.columns) - set(node_map) - set(foreign))
    _cfsum = cf.groupby("county_st").cf.sum()
    mo.vstack([
        mo.hstack([
            mo.stat(f"{data.shape[1]}",label="Nodes",
                caption=f"{len(_new)} not in nearest-node map"),
            mo.stat(f"{cf.county_st.nunique()}",label="Counties",
                caption=f"{(_split>1).sum()} split among several nodes"),
            mo.stat(f"{_changed}",label="Counties remapped",
                caption="largest share not on nearest node"),
            mo.stat(f"{len(foreign)}",label="Foreign nodes",
                caption=", ".join(f"{x} ({y})" for x,y in foreign.items())),
            mo.stat(f"{_total.max()/1e3:.1f} GW",label="WECC peak",
                caption=f"{_total.idxmax():%Y-%m-%d %H:%M} UTC"),
        ],justify="start"),
        mo.md("**Annual WECC energy (TWh):** "
            + ", ".join(f"{t:%Y}: {e}" for t,e in _energy.items())
            + "  \n**Annual foreign energy (TWh):** "
            + ", ".join(f"{t:%Y}: {e}" for t,e in
                (data[list(foreign)].sum(axis=1).resample("YS").sum()/1e6).round(1).items())
            + f"  \n**Contribution factor sums:** min {_cfsum.min():.6f}, max {_cfsum.max():.6f}"
            + f"  \n**Data:** {data.index[0]} to {data.index[-1]}, {len(data)} hours,"
            + f" missing values {int(data.isna().sum().sum())}, negative values {int((data<0).sum().sum())}"),
    ])
    return


@app.cell
def _(cf, counties, data, foreign, nodes, node_map, pd, plt, states):
    # map of county-to-node allocations
    def _map():
        fig,ax = plt.subplots(figsize=(10,10))
        for _state in states:
            _geometry = _state["geometry"]
            _polygons = _geometry["coordinates"] if _geometry["type"] == "MultiPolygon" \
                else [_geometry["coordinates"]]
            for _polygon in _polygons:
                _lon,_lat = zip(*_polygon[0])
                ax.plot(_lon,_lat,color="k",linewidth=0.6,alpha=0.5,zorder=0)
        for _,row in cf.iterrows():
            if row.county_st not in counties.index or row.node not in nodes.index:
                continue
            c,n = counties.loc[row.county_st],nodes.loc[row.node]
            ax.plot([c.LON,n.LON],[c.LAT,n.LAT],
                color="tab:orange" if row.method=="bus" else "tab:gray",
                alpha=0.2+0.6*row.cf,linewidth=0.5+2*row.cf)
        ax.scatter(counties.LON,counties.LAT,s=4,color="k",label="County centroid")
        _mean = data.mean()
        _xy = nodes.reindex(_mean.index)
        _ext = _mean.index.isin(set(foreign))
        _old = _mean.index.isin(set(node_map)) & ~_ext
        ax.scatter(_xy.LON[_old],_xy.LAT[_old],s=_mean[_old]/10,alpha=0.6,
            color="tab:blue",label="Node in nearest-node map")
        _add = ~_old & ~_ext
        ax.scatter(_xy.LON[_add],_xy.LAT[_add],s=_mean[_add]/10,alpha=0.6,
            color="tab:red",label="Node added by bus split")
        ax.scatter(_xy.LON[_ext],_xy.LAT[_ext],s=_mean[_ext]/10,alpha=0.6,
            color="tab:green",label="Foreign node")
        for _node in _mean.index[_ext]:
            ax.annotate(f"{_node} ({foreign[_node]})",(_xy.LON[_node],_xy.LAT[_node]),
                textcoords="offset points",xytext=(8,-12),fontsize=8)
        ax.plot([],[],color="tab:orange",label="bus allocation")
        ax.plot([],[],color="tab:gray",label="nearest allocation")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        _lon = pd.concat([counties.LON,_xy.LON])
        _lat = pd.concat([counties.LAT,_xy.LAT])
        ax.set_xlim(_lon.min()-1,_lon.max()+1)
        ax.set_ylim(_lat.min()-1,_lat.max()+1)
        ax.set_aspect(1.25)
        ax.grid(alpha=0.3)
        ax.legend(loc="lower left")
        ax.set_title("County-to-node allocation (marker area ~ mean node load)")
        return fig
    map_fig = _map()
    return (map_fig,)


@app.cell
def _(cf, data, foreign, mo, node_map, pd):
    # tables
    _mean = data.mean()
    _split = cf[cf.groupby("county_st").node.transform("count")>1].copy()
    _split["nearest_node"] = _split.county_st.map(node_map)
    split_table = _split.round({"cf":4}).reset_index(drop=True)

    _top = cf.loc[cf.groupby("county_st").cf.idxmax()].set_index("county_st")
    _top["nearest_node"] = node_map.reindex(_top.index)
    remap_table = _top[_top.node!=_top.nearest_node].rename(
        columns={"node":"largest_node","cf":"largest_cf"}).round({"largest_cf":4}).reset_index()

    node_table = pd.DataFrame({
        "counties":cf.groupby("node").county_st.apply(lambda x:", ".join(x)),
        "county_count":cf.groupby("node").county_st.count(),
        "foreign":pd.Series(foreign),
        "mean_MW":_mean.round(1),
        "peak_MW":data.max().round(1),
        "min_MW":data.min().round(1),
        }).rename_axis("node")
    node_table["county_count"] = node_table["county_count"].fillna(0).astype(int)
    node_table.insert(3,"in_nearest_map",node_table.index.isin(set(node_map)))
    node_table = node_table.sort_values("mean_MW",ascending=False).reset_index()
    mo.md("")
    return node_table, remap_table, split_table


@app.cell
def _(map_fig, mo, node_table, remap_table, split_table):
    mo.ui.tabs({
        "Map":map_fig,
        "Split counties":mo.vstack([
            mo.md("Counties allocated to more than one node, with the node used by the nearest-node map."),
            mo.ui.table(split_table,page_size=25,selection=None)]),
        "Remapped counties":mo.vstack([
            mo.md("Counties whose largest allocation is not their nearest load node."),
            mo.ui.table(remap_table,page_size=25,selection=None)]),
        "Nodes":mo.ui.table(node_table,page_size=25,selection=None),
    })
    return


@app.cell
def _(data, mo):
    # node and period selection
    node_ui = mo.ui.dropdown(options=sorted(data.columns),
        value=data.mean().idxmax(),label="Node:")
    resample_ui = mo.ui.dropdown(options={"Hourly":"1h","Daily":"1D","Monthly":"MS"},
        value="Daily",label="Resolution:")
    year_ui = mo.ui.dropdown(options=["All"]+sorted({str(x.year) for x in data.index}),
        value="All",label="Year:")
    mo.hstack([node_ui,resample_ui,year_ui],justify="start")
    return node_ui, resample_ui, year_ui


@app.cell
def _(cf, data, foreign, mo, node_ui, plt, resample_ui, year_ui):
    # node load profile and contributing counties
    _series = data[node_ui.value]
    if year_ui.value != "All":
        _series = _series.loc[year_ui.value]
    _how = resample_ui.value
    plt.close()
    _fig,_ax = plt.subplots(figsize=(10,4))
    if _how == "1h":
        _series.plot(ax=_ax,linewidth=0.5)
    else:
        _r = _series.resample(_how)
        _r.mean().plot(ax=_ax,label="mean")
        _ax.fill_between(_r.max().index,_r.min(),_r.max(),alpha=0.3,label="min/max")
        _ax.legend()
    _ax.set_ylabel("Load (MW)")
    _ax.set_xlabel("Date/Time (UTC)")
    _ax.set_title(f"Node {node_ui.value}")
    _ax.grid(alpha=0.3)
    _counties = cf[cf.node==node_ui.value][["county_st","cf","method"]].round({"cf":4})
    _foreign = (f"Includes the {foreign[node_ui.value]} load from `wecc240`"
        f" `{foreign[node_ui.value]}/{node_ui.value}.csv`."
        if node_ui.value in foreign else "")
    mo.vstack([
        _fig,
        mo.md(f"**Counties contributing to node {node_ui.value}**  \n{_foreign}"),
        mo.ui.table(_counties.reset_index(drop=True),selection=None),
    ])
    return


@app.cell
def _():
    import marimo as mo
    import importlib.util
    import json
    import pathlib
    import urllib.request
    import pandas as pd
    import matplotlib.pyplot as plt
    from cache import Cache

    return Cache, importlib, json, mo, pathlib, pd, plt, urllib


if __name__ == "__main__":
    app.run()
