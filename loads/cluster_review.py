import marimo

__generated_with = "0.20.2"
app = marimo.App(width="medium")


@app.cell
def _(mo):
    mo.md(r"""
    This notebook performs clustering of WECC counties based on climate and load data.
    """)
    return


@app.cell
def _(Total, cluster_ui, mo):
    # variable selection
    _options = sorted(Total.COLUMNS)#[x for x in Total.COLUMNS if x.endswith("_MW")])
    variable_ui = mo.ui.dropdown(options=_options,value="elec_total_MW",label="Clustering variable:")

    mo.hstack([variable_ui,cluster_ui],justify='start')
    return (variable_ui,)


@app.cell
def _(clusters, county_loads, members_ui, mo, normalize_ui, selection, svd_ui):
    # main tabs UI
    mo.ui.tabs(
        {
            "Load data": mo.vstack([mo.hstack([selection,svd_ui]), county_loads]),
            "Cluster medoids": mo.vstack([normalize_ui,clusters]),
            "County assignments": members_ui,
        },
        lazy=True,
    )
    return


@app.cell
def _(Cluster, Counties, cluster_ui, mo, np, variable_ui):
    # counties clustering
    counties = [
        f"{y} {x}"
        for x, y in Counties(use_index="RO", selection="WECC")[
            ["ST", "COUNTY"]
        ].values
    ]
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
    cluster_ui = mo.ui.slider(start=1,stop=10,step=1,debounce=True,value=6,label="Number of k-means clusters:")
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
def _(closest, cluster, counties, label_ui):
    # members of clusters
    members = {n+1:m for n,m in enumerate(cluster.members)}
    members[None] = counties
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

    return Cluster, Counties, Total, mo, np, pd, plt, seaborn


if __name__ == "__main__":
    app.run()
