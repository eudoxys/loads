"""The loads.skill pipeline on a synthetic, Total-shaped frame (no network).

Shows validate -> summarize -> calibrate -> aggregate -> export on data
with the same columns and conventions `loads.Total` returns, so the flow
can be tried anywhere. Replace `synthetic()` with `ls.training(...)` or
`ls.county_loads(...)` when data access is available.

    python3 loads/skill/examples/offline_demo.py
"""

import os
import tempfile

import numpy as np
import pandas as pd

import loads.skill as ls


def synthetic(year: int, scale: float = 1.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = ls.hourly_range(year)
    h = np.arange(len(idx))
    temp = 60 + 20 * np.sin(2 * np.pi * (h / len(h) - 0.3)) + 8 * np.sin(2 * np.pi * (h % 24 - 21) / 24)
    sun = np.clip(np.sin(2 * np.pi * ((h - 14) % 24) / 24), 0, None)
    df = pd.DataFrame(index=idx)
    df["elec_residential_MW"] = scale * (400 + 6 * np.abs(temp - 65) + rng.normal(0, 5, len(h)))
    df["elec_commercial_MW"] = scale * (500 + 4 * np.clip(temp - 60, 0, None) + rng.normal(0, 5, len(h)))
    df["elec_industrial_MW"] = scale * 223.6
    df["elec_agricultural_MW"] = scale * 6.9
    df["elec_transportation_MW"] = 0.0
    df["elec_dg_MW"] = -40 * scale * sun
    df["elec_total_MW"] = df.filter(regex=r"^elec_(res|com|ind|agr|tra)").sum(axis=1)
    df["elec_net_MW"] = df["elec_total_MW"] + df["elec_dg_MW"]
    df["temperature_degF"] = temp.round(1)
    return df


def main() -> None:
    places = {"Alameda CA": 1.0, "Contra Costa CA": 0.8, "Los Angeles CA": 4.0}
    frames = {name: synthetic(2020, k, seed=i) for i, (name, k) in enumerate(places.items())}

    for name, df in frames.items():
        rep = ls.validate(df, require_full_years=True)
        print(name, "valid" if rep.ok else rep)

    s = ls.summary(frames["Alameda CA"], "elec_net_MW")
    print(f"Alameda net: {s['energy_MWh'] / 1e3:,.0f} GWh, peak {s['peak_MW']:.0f} MW "
          f"at {s['peak_time']}, load factor {s['load_factor']:.2f}")

    sectors = [c for c in frames["Alameda CA"] if c.startswith("elec_")
               and c not in ("elec_total_MW", "elec_dg_MW", "elec_net_MW")]
    cal, k = ls.scale_to_energy(frames["Alameda CA"], {"elec_total_MW": 10.0e6},
                                also_scale={"elec_total_MW": sectors})
    print(f"calibration factor {k['elec_total_MW']:.3f}; still valid: {ls.validate(cal).ok}")

    nodes = pd.DataFrame({"lat": [37.9, 34.0], "lon": [-122.2, -118.2]}, index=["bay_area", "socal"])
    mapping = ls.nearest_nodes(list(places), nodes)
    nodal = ls.allocate({n: f["elec_net_MW"] for n, f in frames.items()}, mapping)
    err = ls.conservation_error({n: f["elec_net_MW"] for n, f in frames.items()}, nodal)
    print(mapping, f"\nconservation error {err:.3g} MWh")
    cp = ls.coincident_peak(nodal)
    print(f"system peak {cp.attrs['system_peak_MW']:.0f} MW at {cp.attrs['system_peak_time']}")
    print(cp.round(3))

    out = tempfile.mkdtemp()
    path = ls.to_csv(nodal, os.path.join(out, "nodal_2020.csv.gz"), extra={"source": "synthetic demo"})
    print("wrote", path, "and", path + ".meta.json")


if __name__ == "__main__":
    main()
