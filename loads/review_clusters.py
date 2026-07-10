"""County loadshape clustering

This [marimo](https://marimo.io/) notebook performs clustering of WECC
counties based on climate and load data.

Clustering is performed based on the singular value decomposition (SVD) of the
specified load variable, which can be either one of the exogenous weather
variables or the endogenous load variables.  The number of cluster can be
selected as well.

- The **Load data** tab presents a "heat map" of MW loads for the selected
  county with hour of day on the horizontal axis and day of year on the
  vertical axis.  The $U$ matrix of the SVD result is also shown with a
  control to select which column of $U$ is plotted. If a particular cluster
  is selected only the counties in that cluster are listed and the medoid
  county is shown by default.

- The **Cluster medoids** tab plots the medoid county loadshape for each
  cluster, either as raw (MW), mean-normalized (pu.MW), or peak-normalized
  (pu.MW).

- The **County assignments** tab provides a downloadable table of which
  counties are assigned to each cluster.

- The **County map** tab displays a map of the US showing which counties were
  grouped together in clusters. Note that the map can be very large and may
  take a few seconds to display.
"""

import marimo

__generated_with = "0.20.2"
app = marimo.App(width="medium", app_title="County Loadshape Clustering")


@app.cell
def _(mo):
    docs = __doc__.split("\n")
    mo.md(f"# {docs[0]}")
    return (docs,)


@app.cell
def _(Total, cluster_ui, mo):
    # variable selection
    _options = sorted(Total.COLUMNS)#[x for x in Total.COLUMNS if x.endswith("_MW")])
    variable_ui = mo.ui.dropdown(options=_options,value="elec_total_MW",label="Clustering variable:")

    mo.hstack([variable_ui,cluster_ui],justify='start')
    return (variable_ui,)


@app.cell
def _(
    clusters,
    county_loads,
    docs,
    fig,
    members_ui,
    mo,
    normalize_ui,
    selection,
    svd_ui,
):
    # main tabs UI
    mo.ui.tabs(
        {
            "Load data": mo.vstack([mo.hstack([selection,svd_ui]), county_loads]),
            "Cluster medoids": mo.vstack([normalize_ui,clusters]),
            "County assignments": members_ui,
            "County map": fig,
            "Help": mo.md("\n".join(docs[1:])),
        },
        lazy=True,
    )
    return


@app.cell
def _(Cluster, Counties, cluster_ui, mo, np, variable_ui):
    # counties clustering
    counties = {
        f"{y} {x}":z
        for x, y, z in Counties(use_index="RO", selection="WECC")[
            ["ST", "COUNTY","FIPS"]
        ].values}
    with mo.status.progress_bar(
        collection=counties, title="Reading county data...", remove_on_exit=True
    ) as _bar:
        cluster = Cluster(
            counties,
            variable_ui.value,
            preprocess=np.abs,
            progress=lambda x: _bar.update(subtitle=x),
        )
    kmeans = cluster.kmeans(n_clusters=cluster_ui.value)
    closest = cluster.closest
    return closest, cluster, counties, kmeans


@app.cell
def _(mo):
    # clustering UI
    cluster_ui = mo.ui.slider(start=1,stop=10,step=1,debounce=True,show_value=True,value=6,label="Number of k-means clusters:")
    return (cluster_ui,)


@app.cell
def _(cluster, mo):
    _options = [("None (MW)",cluster.L),("Mean (pu.MW)",cluster.M),("Peak (pu.MW)",cluster.P)]
    normalize_ui = mo.ui.radio(label="Plot normalization:",options=dict(_options),inline=True,value=_options[0][0])
    return (normalize_ui,)


@app.cell
def _(closest, cluster, cluster_ui, normalize_ui, plt):
    # clustering tab plot
    plt.figure(figsize=(10,7))
    plt.clf()
    for x in closest:
        plt.plot(normalize_ui.value[x], label=f"{cluster.C[x]}")
    plt.gca().set_ylabel("Mean loadshape")
    plt.legend()
    plt.gca().set_xlabel("Hour of day (UTC)")
    plt.title(f"$k$-Means cluster medoids ($k={cluster_ui.value}$)")
    plt.grid()
    clusters = plt.gca()
    return (clusters,)


@app.cell
def _(cluster, mo, pd):
    members_ui = mo.ui.table(pd.DataFrame(cluster.members,index=cluster.medoids).fillna("").T,
                selection=None,
                page_size=16,
                show_data_types=False,
                             show_column_summaries=False,
               )
    return (members_ui,)


@app.cell
def _(cluster, pd):
    clusters_df = pd.DataFrame(cluster.members,index=cluster.medoids).stack().reset_index().drop("level_1",axis=1).rename({"level_0":"medoid",0:"county_st"},axis=1).dropna().set_index("county_st")
    clusters_df.to_csv("clusters.csv")
    return


@app.cell
def _(closest, cluster, counties, label_ui):
    # members of clusters
    members = {n+1:m for n,m in enumerate(cluster.members)}
    members[None] = list(counties)
    default = members[None][0] if label_ui.value is None else cluster.C[closest[label_ui.value-1]]
    return default, members


@app.cell
def _(default, label_ui, members, mo):
    # states UI based on cluster members
    _options = sorted(set([x.split(" ")[-1] for x in members[label_ui.value]]))
    state_ui = mo.ui.dropdown(options=_options,value=default.split(" ")[-1],label="State:")
    return (state_ui,)


@app.cell
def _(cluster, cluster_ui, default, label_ui, members, mo, state_ui):
    # county UI based on cluster members
    if cluster_ui.value is None:
        _counties = [x for x in cluster.C if x.endswith(state_ui.value)]
    else:
        _counties = [x for x in members[label_ui.value] if x.endswith(state_ui.value)]
    county_ui = mo.ui.dropdown(options=sorted(_counties),value=default if default.endswith(state_ui.value) else _counties[0],label="County:")
    return (county_ui,)


@app.cell
def _(closest, cluster, cluster_ui, kmeans, np):
    # save medoids data to file for later processing
    medoids = [cluster.C[x] for x in closest]
    weights = np.zeros(cluster_ui.value)
    for _n, _m in enumerate(kmeans.labels_):
        weights[_m] += cluster.W[_n]
    return


@app.cell
def _(cluster_ui, mo):
    # cluster label UI
    label_ui = mo.ui.dropdown(options=range(1,cluster_ui.value+1),label="Cluster:")
    return (label_ui,)


@app.cell
def _(Total, county_ui, state_ui):
    # data from state and county UI
    state = state_ui.value
    county = " ".join(county_ui.value.split(" ")[:-1])
    data = Total(state,county)
    return county, data, state


@app.cell
def _(county_ui, label_ui, mo, state_ui):
    # data selection UI
    selection = mo.hstack([state_ui,county_ui,label_ui],justify="start")
    return (selection,)


@app.cell
def _(cluster, mo):
    svd_ui = mo.ui.slider(label="$U$-column",steps=range(cluster.U.shape[1]//24),value=0,debounce=True,show_value=True)
    return (svd_ui,)


@app.cell
def _(county, data, np, plt, seaborn, state, svd_ui, variable_ui):
    # plot data for selected state and county
    load = np.reshape(data.elec_total_MW.values,(365,24))
    _u,_d,_l = np.linalg.svd(load.T)

    plt.figure(figsize=(16,8))
    plt.suptitle(f"{state} {county}")

    plt.subplot(1,2,2)
    plt.plot(_u[:,svd_ui.value])
    plt.grid()
    plt.gca().set_xlabel("Hour of day (UTC)")
    plt.gca().set_ylabel(f"U[:,{svd_ui.value}]")
    plt.title(f"{variable_ui.value} decomposition $U_{svd_ui.value}$")

    plt.subplot(1,2,1)
    ax = seaborn.heatmap(load)
    ax.set_ylabel("Day of year")
    ax.set_xlabel("Hour of day (UTC)")
    plt.title(f"{variable_ui.value} heatmap")

    county_loads = plt.gca()
    return (county_loads,)


@app.cell
def _(cluster, counties, json, pd, px, urlopen):
    # county map
    with urlopen(
        "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
    ) as response:
        _counties = json.load(response)

    _df = pd.DataFrame(
        {
            "fips": counties.values(),
            "county": counties.keys(),
            "cluster": [cluster.medoids[x] for x in cluster.cluster.labels_],
        }
    )

    fig = px.choropleth(_df,
        geojson=_counties,
        locations="fips",
        hover_data={"county":True, "cluster":True, "fips":False},
        color="cluster",
        scope="usa",
        labels={"cluster": "Cluster", "county": "County", "fips":"FIPS"},
    )
    fig.update_geos(center={"lat":40,"lon":-115},projection_scale=1,lonaxis_range=[-125,-100])
    fig.update_layout(height=500,width=800,margin={"r": 0, "t": 0, "l": 0, "b": 0});
    return (fig,)


@app.cell
def _():
    # modules
    import marimo as mo
    import numpy as np
    import pandas as pd
    import datetime as dt
    import matplotlib.pyplot as plt
    import seaborn
    from loads import Total
    from loads import Cluster
    from fips import Counties
    from urllib.request import urlopen
    import json
    import plotly.express as px
    # from review_cluster import __doc__
    return (
        Cluster,
        Counties,
        Total,
        json,
        mo,
        np,
        pd,
        plt,
        px,
        seaborn,
        urlopen,
    )


if __name__ == "__main__":
    app.run()
