"""Command line for shell-driven workflows. Prints JSON on stdout.

    python3 -m loads.skill resolve "Alameda County, CA"
    python3 -m loads.skill env
    python3 -m loads.skill county "Alameda CA" 2020 --sectors -o alameda_2020.csv
    python3 -m loads.skill series "Alameda CA" 2020 --column elec_total_MW \\
        --mode percentile --samples 200 --percentile 95 -o p95.csv
    python3 -m loads.skill validate alameda_2020.csv
    python3 -m loads.skill summarize alameda_2020.csv --column elec_net_MW
    python3 -m loads.skill wecc "Alameda CA" "Washoe NV" --years 2020 -o wecc_2020.csv

Unlike `loads print -Y 2020`, which silently ignores `-Y` for the total
dataset and prints 2018 training data, `county`/`series` honor the years.
`wecc` reads the precomputed 2018-2022 WECC county estimate (no model fit, no
NSRDB credentials; needs the `loads/wecc` data files of a repository clone).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys


def _years(text: str) -> list[int]:
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def _emit(obj) -> None:
    json.dump(obj, sys.stdout, indent=2, default=str, ensure_ascii=False)
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m loads.skill", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resolve", help="resolve a place name to state/county")
    r.add_argument("place")

    e = sub.add_parser("env", help="report cache folder and NSRDB credentials")
    e.add_argument("--cachedir")

    c = sub.add_parser("county", help="county frame: total, DG, net (and sectors)")
    c.add_argument("place")
    c.add_argument("years", help="e.g. 2020, 2019-2021, 2018,2020")
    c.add_argument("--sectors", action="store_true")
    c.add_argument("--no-dg", action="store_true")
    c.add_argument("--dg-source", choices=["model", "eia"], default="model",
                   help="elec_dg_MW from the TSGAM stock-PV model or loads.dgen.DG (EIA-861M)")
    c.add_argument("--total", choices=["direct", "sum"])
    c.add_argument("--edges", choices=["fill", "pad", "nan"], default="fill")
    c.add_argument("--cachedir")
    c.add_argument("-o", "--output", required=True)

    s = sub.add_parser("series", help="one Total target in a chosen mode")
    s.add_argument("place")
    s.add_argument("years")
    s.add_argument("--column", default="elec_total_MW")
    s.add_argument("--mode", choices=["predict", "sample", "percentile", "samples", "training"], default="predict")
    s.add_argument("--samples", type=int, default=100)
    s.add_argument("--percentile", type=float, default=50.0)
    s.add_argument("--edges", choices=["fill", "pad", "nan"], default="fill")
    s.add_argument("--cachedir")
    s.add_argument("-o", "--output", required=True)

    v = sub.add_parser("validate", help="check a CSV against the loads contract")
    v.add_argument("path")
    v.add_argument("--full-years", action="store_true")

    m = sub.add_parser("summarize", help="energy, peak and load factor of a CSV")
    m.add_argument("path")
    m.add_argument("--column", default="elec_total_MW")
    m.add_argument("--freq", default="MS")

    w = sub.add_parser("wecc", help="precomputed WECC county gross load, 2018-2022")
    w.add_argument("places", nargs="*", help="counties (default all 407)")
    w.add_argument("--years", help="e.g. 2020, 2019-2021 (default all)")
    w.add_argument("--dg", action="store_true", help="write rooftop PV (elec_dg_MW sign) instead of gross load")
    w.add_argument("--scaled", action="store_true", help="with --dg: EIA-scaled DG (county_dg_scaled.csv.gz)")
    w.add_argument("-o", "--output", required=True)

    a = p.parse_args(argv)

    if a.cmd == "resolve":
        from .locations import resolve
        c_ = resolve(a.place)
        _emit({**dataclasses.asdict(c_), "county_st": c_.county_st})
        return 0

    if a.cmd == "env":
        from .fetch import configure
        _emit(configure(a.cachedir, require_credentials=False))
        return 0

    if a.cmd in ("county", "series"):
        from . import fetch
        from .export import to_csv
        from .validate import validate
        fetch.configure(a.cachedir)
        if a.cmd == "county":
            df = fetch.county_loads(a.place, _years(a.years), dg=not a.no_dg, dg_source=a.dg_source,
                                    sectors=a.sectors,
                                    total=a.total, edges=a.edges)
        else:
            df = fetch.series(a.place, _years(a.years), a.column, mode=a.mode, samples=a.samples,
                              percentile=a.percentile, edges=a.edges)
        to_csv(df, a.output)
        rep = validate(df)
        _emit({"output": a.output, "rows": len(df), "columns": list(df.columns),
               "valid": rep.ok, "issues": [str(i) for i in rep.issues],
               "provenance": df.attrs.get("loadskill")})
        return 0 if rep.ok else 2

    if a.cmd == "wecc":
        from .export import to_csv
        from .wecc import wecc_dg, wecc_estimate
        places = a.places or None
        years = _years(a.years) if a.years else None
        if a.dg:
            df = wecc_dg(places, years, scaled=a.scaled)
        else:
            df = wecc_estimate(places, years)
        to_csv(df, a.output, precision=4)
        _emit({"output": a.output, "rows": len(df), "columns": len(df.columns),
               "provenance": df.attrs.get("loadskill")})
        return 0

    if a.cmd == "validate":
        from .export import read_csv
        from .validate import validate
        rep = validate(read_csv(a.path), require_full_years=a.full_years)
        _emit({"valid": rep.ok, "rows": rep.rows, "issues": [str(i) for i in rep.issues]})
        return 0 if rep.ok else 2

    if a.cmd == "summarize":
        from .export import read_csv
        from .summarize import energy, summary
        df = read_csv(a.path)
        _emit({"summary": summary(df, a.column),
               "energy_MWh": {str(k): v for k, v in
                              energy(df, a.freq, [a.column]).iloc[:, 0].round(3).items()}})
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
