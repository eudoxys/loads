"""Synthetic `loads.Total`-shaped frames for the offline `loads.skill` tests"""

import numpy as np
import pandas as pd


def synthetic_total(year: int = 2018, seed: int = 0) -> pd.DataFrame:
    """A frame shaped like `loads.Total` training output, built offline."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="1h", tz="UTC", name="timestamp")
    h = np.arange(len(idx))
    temp = 60 + 20 * np.sin(2 * np.pi * (h / 8760 - 0.3)) + 8 * np.sin(2 * np.pi * (h % 24 - 9) / 24)
    sun = np.clip(np.sin(2 * np.pi * ((h - 14) % 24) / 24), 0, None)
    res = 400 + 6 * np.abs(temp - 65) + 80 * np.sin(2 * np.pi * (h % 24 - 12) / 24) + rng.normal(0, 5, len(h))
    com = 500 + 4 * np.clip(temp - 60, 0, None) + 150 * ((h % 24 >= 15) | (h % 24 <= 1)) + rng.normal(0, 5, len(h))
    df = pd.DataFrame(
        {
            "temperature_degF": temp.round(1),
            "humidity_pc": np.clip(60 + rng.normal(0, 10, len(h)), 0, 100).round(1),
            "global_Wpms": (800 * sun).round(0),
            "direct_Wpms": (700 * sun).round(0),
            "diffuse_Wpms": (100 * sun).round(0),
            "elec_dg_MW": (-40 * sun).round(3),
            "elec_residential_MW": res.round(3),
            "elec_commercial_MW": com.round(3),
            "elec_industrial_MW": 223.618,
            "elec_agricultural_MW": 6.901,
            "elec_transportation_MW": 0.0,
        },
        index=idx,
    )
    sectors = [f"elec_{s}_MW" for s in ("residential", "commercial", "industrial", "agricultural", "transportation")]
    df["elec_total_MW"] = df[sectors].sum(axis=1)
    df["elec_net_MW"] = df["elec_total_MW"] + df["elec_dg_MW"]
    return df
