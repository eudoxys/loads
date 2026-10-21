"""Scale WECC county rooftop PV to EIA small-scale solar generation

Builds `county_dg_scaled.csv.gz` from `county_dg.csv`:

  1. Counties that `county_dg.csv` lacks get their state's DG profile in
     proportion to their share of the state's 2020 gross load (the cached
     validation load matrix `loads/0/_validate/calibrate_X_2020.csv.gz`).

  2. Each state's DG is scaled, year by year (UTC calendar years), so its
     annual energy equals EIA's estimated small-scale solar generation
     (`eia_smallscale_pv.csv`, Electric Power Annual Table 3.21, all sectors,
     GWh) times the WECC share of the state. Hours after 2022 use the 2022
     factor.

The county distribution within each state and the hourly shapes are kept.
Values are positive MW (DG output), as in `county_dg.csv`. The factors are
written to `county_dg_scaling.csv`.

Usage
-----

    python3 loads/wecc/county_dg_scale.py

Caveats
-------

  - Texas: only El Paso County is in WECC; its share of the state is taken as
    its 2020 Census population share (865,657 of 29,145,505).

  - South Dakota: only Custer, Fall River and Lawrence Counties are in WECC;
    their share of the state is taken as their 2020 Census population share
    (41,059 of 886,667). EIA reports only 1-2 GWh statewide.
"""

# pylint: disable=invalid-name
import os
import sys

import pandas as pd

FOLDER = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(FOLDER)
WECC_SHARE = {"TX": 865657 / 29145505, "SD": (8318 + 6973 + 25768) / 886667}


def main() -> pd.DataFrame:
    """Build and save the scaled county DG"""
    sys.path.insert(0,os.path.join(PACKAGE,"_validate"))
    import validate_calibrate as vc # pylint: disable=import-outside-toplevel,import-error

    dg = pd.read_csv(os.path.join(FOLDER,"county_dg.csv"),index_col=[0],parse_dates=[0])
    dg.index = pd.DatetimeIndex(dg.index).tz_convert("UTC")
    dg.index.name = "timestamp"
    eia = pd.read_csv(os.path.join(FOLDER,"eia_smallscale_pv.csv"),index_col=[0])
    eia.columns = [int(x) for x in eia.columns]
    units = [f"{c} {s}" for s,c in vc.wecc_units()]
    energy = vc.gross_load(2020).sum()
    state = pd.Series({x:x.rsplit(" ",1)[1] for x in units})

    # fill counties without DG from their state's profile, by load share
    data = dg.reindex(columns=units)
    for st,members in state.groupby(state):
        have = [x for x in members.index if x in dg.columns]
        missing = [x for x in members.index if x not in dg.columns]
        if not missing:
            continue
        profile = dg[have].sum(axis=1) / energy[have].sum() if have else 0.0
        for unit in missing:
            data[unit] = profile * energy[unit]
    data = data.fillna(0.0)

    # scale each state-year to EIA small-scale generation
    years = data.index.year.where(data.index.year <= max(eia.columns),max(eia.columns))
    rows = []
    for st,members in state.groupby(state):
        cols = list(members.index)
        for year in eia.columns:
            mask = years == year
            model = data.loc[data.index.year == year,cols].sum().sum() / 1e3 # GWh
            target = eia.loc[st,year] * WECC_SHARE.get(st,1.0)
            factor = target / model if model > 0 else 1.0
            data.loc[mask,cols] *= factor
            rows.append({"state":st,"year":year,"eia_GWh":eia.loc[st,year],
                "wecc_share":WECC_SHARE.get(st,1.0),"target_GWh":target,
                "model_GWh":model,"factor":factor})
    factors = pd.DataFrame(rows).set_index(["state","year"])
    data.to_csv(os.path.join(FOLDER,"county_dg_scaled.csv.gz"),index=True,header=True,
        float_format="%.3f",compression="gzip")
    factors.to_csv(os.path.join(FOLDER,"county_dg_scaling.csv"),float_format="%.4f")
    return factors


if __name__ == "__main__":

    print(main().round(3).to_string())
