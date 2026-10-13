import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    This notebook allows you to review the uncalibrated commercial building load data for individual counties.
    """)
    return


@app.cell
def _(Counties):
    counties = Counties(use_index="SYSTEM", selection="WECC")
    counties["COUNTY_ST"] = [f"{x} {y}" for x,y in counties[["COUNTY","ST"]].values]
    states = counties.ST.unique().tolist()
    state_counties = {x:counties[counties.ST==x]["COUNTY"].tolist() for x in states}
    return state_counties, states


@app.cell
def _(mo, states):
    state_ui = mo.ui.dropdown(options=states,value=states[0])
    return (state_ui,)


@app.cell
def _(mo, state_counties, state_ui):
    state = state_ui.value
    _options = state_counties[state]
    county_ui = mo.ui.dropdown(options=_options,value=_options[0])
    return county_ui, state


@app.cell
def _(dt, mo):
    year_ui = mo.ui.dropdown(options=range(2018,dt.datetime.now().year),value=2018)
    return (year_ui,)


@app.cell
def _(county_ui, mo, state_ui, year_ui):
    mo.hstack([state_ui,county_ui,year_ui],justify="start")
    return


@app.cell
def _(Commercial, county_ui, mo, state, year_ui):
    county = county_ui.value
    year = year_ui.value
    with mo.status.spinner("Reading building enduse data"):
        data = Commercial(state,county,year)
    return (data,)


@app.cell
def _(data):
    data
    return


@app.cell
def _():
    import marimo as mo
    import datetime as dt
    from fips import Counties
    from loads.commercial import Commercial

    return Commercial, Counties, dt, mo


if __name__ == "__main__":
    app.run()
