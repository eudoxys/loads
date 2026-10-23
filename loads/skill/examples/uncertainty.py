"""Peak and energy distributions from a TSGAM sample ensemble.

Needs data access and NSRDB credentials.

    python3 loads/skill/examples/uncertainty.py "Alameda CA" 2021 50
"""

import sys

import loads.skill as ls


def main(place: str, year: int, n: int) -> None:
    ls.configure()
    c = ls.resolve(place)

    expected = ls.series(c, year)                                  # samples=0
    ens = ls.series(c, year, mode="samples", samples=n)            # sample_0..n-1
    S = ens.filter(like="sample_")

    peaks = S.max()
    energy = S.sum() / 1e3                                         # GWh
    print(f"{c.county_st} {year}, {n} realizations")
    print(f"expected-load peak   {expected['elec_total_MW'].max():8.1f} MW (biased low)")
    print(f"realized peak  P10/P50/P90  {peaks.quantile([.1, .5, .9]).round(1).tolist()} MW")
    print(f"annual energy  P10/P50/P90  {energy.quantile([.1, .5, .9]).round(1).tolist()} GWh")

    band = S.quantile([0.1, 0.5, 0.9], axis=1).T
    band.columns = ["p10_MW", "p50_MW", "p90_MW"]
    band.attrs = ens.attrs
    ls.to_csv(band, f"out/{c.state}_{c.county.replace(' ', '_')}_{year}_band.csv.gz",
              extra={"note": "per-hour quantiles; not trajectories"})


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 50)
