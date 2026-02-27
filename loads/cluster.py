import marimo

__generated_with = "0.19.6"
app = marimo.App(width="medium")


@app.cell
def _(mo):
    mo.md(r"""
    This notebook perform holdout testing of the TSGAM load model on the medoid counties for the selected number of county clusters.
    """)
    return


@app.cell
def _(Counties, Total, mo, np):
    # load county data into U and C arrays
    U = [] # u-matrix from SVD
    C = [] # county name
    W = [] # county weight
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
        W.append(float(_load.sum()/1e6))
        U.append(_u[:,0])
        C.append(f"{_county} {_state}")
    return C, U, W, counties


@app.cell
def _(mo):
    # clustering UI
    cluster_ui = mo.ui.slider(start=1,stop=10,step=1,debounce=True,value=2,label="Number of k-means clusters:")
    show_ui = mo.ui.radio(label="Show",options=["Centroids","Medoids"],inline=True,value="Centroids")
    mo.hstack([cluster_ui,show_ui],justify="start")
    return cluster_ui, show_ui


@app.cell
def _(C, U, W, cluster_ui, plt, show_ui):
    # clustering analysis results
    from sklearn.cluster import KMeans
    from sklearn.metrics import pairwise_distances_argmin_min
    kmeans = KMeans(n_clusters=cluster_ui.value, n_init="auto", random_state=0).fit(U,sample_weight=W)
    match show_ui.value:
        case "Centroids":
            plt.plot(kmeans.cluster_centers_.T)
        case "Medoids":
            closest, _ = pairwise_distances_argmin_min(kmeans.cluster_centers_, U)
            for x in closest:
                plt.plot(U[x], label=C[x])
            plt.legend()
        case "_":
            raise ValueError(f"{show_ui.value=} invalid")

    plt.grid()
    plt.title(f"k-Means cluster {show_ui.value.lower()} with $k={cluster_ui.value}$")
    plt.xlabel = "Hour of day"

    plt.gca()
    return (kmeans,)


@app.cell
def _(C, cluster_ui, counties, kmeans):
    # members of clusters
    members = {n+1:[C[m] for m,x in enumerate(kmeans.labels_) if x == n] for n in range(cluster_ui.value)}
    members[None] = [f"{y} {x}" for x,y in counties]
    return (members,)


@app.cell
def _(label_ui, members, mo):
    # states UI based on cluster members
    _options = sorted(set([x.split(" ")[-1] for x in members[label_ui.value]]))
    state_ui = mo.ui.dropdown(options=_options,value=_options[0],label="State:")
    return (state_ui,)


@app.cell
def _(C, cluster_ui, label_ui, members, mo, state_ui):
    # county UI based on cluster members
    if cluster_ui.value is None:
        _counties = [" ".join(x.split(" ")[:-1]) for x in C if x.endswith(state_ui.value)]
    else:
        _counties = [" ".join(x.split(" ")[:-1]) for x in members[label_ui.value]]
    county_ui = mo.ui.dropdown(options=sorted(_counties),value=_counties[0],label="County:")
    return (county_ui,)


@app.cell
def _(cluster_ui, mo):
    # cluster label UI
    label_ui = mo.ui.dropdown(options=range(1,cluster_ui.value+1),label="Cluster:")
    return (label_ui,)


@app.cell
def _(Total, county_ui, state_ui):
    # data from state and county UI
    state = state_ui.value
    county = county_ui.value
    data = Total(state,county)
    return county, data, state


@app.cell
def _(county_ui, label_ui, mo, state_ui):
    # data selection UI
    mo.hstack([state_ui,county_ui,label_ui],justify="start")
    return


@app.cell
def _(county, data, np, plt, seaborn, state):
    # plot data for selected state and county
    load = np.reshape(data.elec_total_MW.values,(365,24))
    _u,_d,_l = np.linalg.svd(load.T)

    plt.figure(figsize=(16,8))
    plt.suptitle(f"{state} {county}")

    plt.subplot(1,2,2)
    plt.plot(_u[:,0])
    plt.grid()
    plt.gca().set_xlabel("Hour of day")
    plt.gca().set_ylabel("U[:,0]")
    plt.title("Decomposition")

    plt.subplot(1,2,1)
    ax = seaborn.heatmap(load)
    ax.set_ylabel("Day of year")
    ax.set_xlabel("Hour of day")
    plt.title("Heatmap")

    county_loads = plt.gca()
    return (county_loads,)


@app.cell
def _(county_loads, mo):
    # tabs UI
    mo.ui.tabs({
        "Loads":county_loads,
        "Tests":None,
    })
    return


@app.cell
def _(county, data, mo, state, tsgam):
    # TSGAM holdout test
    mo.stop((data.elec_total_MW==0).all(),mo.md(f"**<font color=red>ERROR**: {county} {state} has no total load data</font>"))
    # Multi-harmonic configuration for time features
    multi_harmonic_config = tsgam.TsgamMultiHarmonicConfig(
        num_harmonics=[6, 4, 3],
        periods=[365.2425 * 24, 7 * 24, 24]
    )

    # Spline configuration for temperature (exogenous variable)
    exog_config: list[tsgam.TsgamSplineConfig | tsgam.TsgamLinearConfig] = [
        tsgam.TsgamSplineConfig(
            knots=[],  # Empty list means knots will be auto-generated from data
            n_knots=10,  # Number of knots to generate
            lags=[-3, -2, -1, 0, 1, 2, 3],
            reg_weight=1e-4,  # Regularization weight for coefficients
            diff_reg_weight=1.0  # Regularization weight for differences between lags
        )
    ]

    # No AR model in baseline (AR is added later in the notebook)
    ar_config = tsgam.TsgamArConfig(
        lags = list(range(1,36))
        )

    # Solver configuration
    solver_config = tsgam.TsgamSolverConfig(
        solver='CLARABEL',
        verbose=False
    )

    # Create main config
    config = tsgam.TsgamEstimatorConfig(
        multi_harmonic_config=multi_harmonic_config,
        exog_config=exog_config,
        ar_config=ar_config,
        solver_config=solver_config,
        random_state=None,
        debug=False
    )

    # Create estimator
    estimator = tsgam.TsgamEstimator(config=config)

    # fit the data
    # estimator.fit(data.temperature_degF.to_frame(),data.elec_total_MW)
    # mo.stop( estimator.problem_.status not in ["optimal","optimal_inaccurate"], f"**<font color=red>ERROR**: fit is {estimator.problem_.status}")
    return


@app.cell
def _():
    # modules
    import marimo as mo
    import numpy as np
    import matplotlib.pyplot as plt
    import seaborn
    from total import Total
    from fips import Counties
    import tsgam_estimator as tsgam
    return Counties, Total, mo, np, plt, seaborn, tsgam


if __name__ == "__main__":
    app.run()
