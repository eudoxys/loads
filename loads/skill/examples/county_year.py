"""One county, one year: fetch, validate, summarize, export.

Needs network access to the `loads` data sources and NSRDB credentials
(see reference/operations.md). First run for a county takes minutes.

    python3 loads/skill/examples/county_year.py "Alameda County, CA" 2020
"""

import json
import sys

import loads.skill as ls


def main(place: str = "Alameda County, CA", year: int = 2020) -> None:
    info = ls.configure()
    print("cache:", info["cachedir"])

    c = ls.resolve(place)
    if c.ambiguous:
        print(f"WARNING: {c.county_st} names more than one place in fips; loads cannot tell them apart")

    df = ls.county_loads(c, year, sectors=True)        # total = sum of sectors
    rep = ls.validate(df, require_full_years=True)
    print(rep)
    rep.raise_if_failed()

    print(json.dumps(ls.summary(df, "elec_net_MW"), indent=2))
    print(ls.energy(df, "MS")[["elec_total_MWh", "elec_dg_MWh", "elec_net_MWh"]].round(0))
    print(ls.daily_profile(df["elec_total_MW"], by="season", tzoffset_hours=c.tzoffset).round(1))

    path = ls.to_csv(df, f"out/{c.state}_{c.county.replace(' ', '_')}_{year}.csv.gz")
    print("wrote", path)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0] if args else "Alameda County, CA", int(args[1]) if len(args) > 1 else 2020)
