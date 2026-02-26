import marimo

__generated_with = "0.19.6"
app = marimo.App(width="medium")


@app.cell
def _(Counties, Total, mo, np):
    U = []
    C = []
    counties = Counties(use_index="RO", selection="WECC")[
            ["ST", "COUNTY"]
        ].values
    for _state, _county in mo.status.progress_bar(
        collection=counties,
        title="Reading WECC county loads",
        remove_on_exit=True,
    ):
        _load = np.reshape(Total(_state, _county).elec_total_MW.values,(365,24)).T
        _u,_d,_l = np.linalg.svd(_load)
        U.append(_u[:,0])
        C.append(f"{_county} {_state}")
    return C, U, counties


@app.cell
def _(mo):
    cluster_ui = mo.ui.slider(start=1,stop=10,step=1,debounce=True,value=2,label="Number of k-means clusters:")
    show_ui = mo.ui.radio(label="Show",options=["Centroids","Medoids"],inline=True,value="Centroids")
    mo.hstack([cluster_ui,show_ui],justify="start")
    return cluster_ui, show_ui


@app.cell
def _(C, U, cluster_ui, plt, show_ui):
    from sklearn.cluster import KMeans
    from sklearn.metrics import pairwise_distances_argmin_min

    kmeans = KMeans(n_clusters=cluster_ui.value, n_init="auto", random_state=0).fit(U)
    match show_ui.value:
        case "Centroids":
            plt.plot(kmeans.cluster_centers_.T)
        case "Medoids":
            closest, _ = pairwise_distances_argmin_min(kmeans.cluster_centers_, U)
            for x in closest:
                plt.plot(U[x], label=C[x])
        case "_":
            raise ValueError(f"{show_ui.value=} invalid")

    plt.grid()
    plt.title(f"k-Means cluster medoids with $k={cluster_ui.value}$")
    plt.xlabel = "Hour of day"

    plt.legend()
    plt.gca()
    return (kmeans,)


@app.cell
def _(C, cluster_ui, counties, kmeans):
    members = {n+1:[C[m] for m,x in enumerate(kmeans.labels_) if x == n] for n in range(cluster_ui.value)}
    members[None] = [f"{y} {x}" for x,y in counties]
    return (members,)


@app.cell
def _(label_ui, members, mo):
    _options = sorted(set([x.split(" ")[-1] for x in members[label_ui.value]]))
    state_ui = mo.ui.dropdown(options=_options,value=_options[0],label="State:")
    return (state_ui,)


@app.cell
def _(C, cluster_ui, label_ui, members, mo, state_ui):
    if cluster_ui.value is None:
        _counties = [" ".join(x.split(" ")[:-1]) for x in C if x.endswith(state_ui.value)]
    else:
        _counties = [" ".join(x.split(" ")[:-1]) for x in members[label_ui.value]]
    county_ui = mo.ui.dropdown(options=sorted(_counties),value=_counties[0],label="County:")
    return (county_ui,)


@app.cell
def _(cluster_ui, mo):
    label_ui = mo.ui.dropdown(options=range(1,cluster_ui.value+1),label="Cluster:")
    return (label_ui,)


@app.cell
def _(Total, county_ui, state_ui):
    state = state_ui.value
    county = county_ui.value
    data = Total(state,county)
    return county, data, state


@app.cell
def _(county_ui, label_ui, mo, state_ui):
    mo.hstack([state_ui,county_ui,label_ui],justify="start")
    return


@app.cell
def _(county, data, np, plt, seaborn, state):
    load = np.reshape(data.elec_total_MW.values,(365,24))
    _u,_d,_l = np.linalg.svd(load.T)

    plt.figure(figsize=(16,8))

    plt.subplot(1,2,2)
    plt.plot(_u[:,0])
    plt.title(f"{state} {county}")
    plt.grid()
    plt.gca().set_xlabel("Hour of day")
    plt.gca().set_ylabel("U[:,0]")

    plt.subplot(1,2,1)
    ax = seaborn.heatmap(load)
    ax.set_ylabel("Day of year")
    ax.set_xlabel("Hour of day")

    plt.gca()
    return


@app.cell
def _():
    import marimo as mo
    import numpy as np
    import matplotlib.pyplot as plt
    import seaborn
    from total import Total
    from fips import Counties
    return Counties, Total, mo, np, plt, seaborn


if __name__ == "__main__":
    app.run()
