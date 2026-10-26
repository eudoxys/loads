"""Exercise `loadskill.fetch` against a stand-in for `loads.Total`.

The stand-in reproduces the output contract read from `loads/total.py`:
`samples=None` -> training frame (ignores date_range); `0`/`1` -> X columns
plus Y; `n>1` with `percentile=None` -> X plus `sample_*`; otherwise X plus Y
at the percentile. Each predicted column has its first 3 / last 3 rows set
to NaN (lag window). Real-data runs are in tests marked `network`.
"""

import numpy as np
import pandas as pd
import pytest

import loads
from loads.skill import fetch, validate
from skill_synthetic import synthetic_total


class FakeTotal(pd.DataFrame):
    EXOGENOUS_VARIABLES = loads.Total.EXOGENOUS_VARIABLES
    cache = {}
    calls = []

    def __init__(self, state, county, *, Y="elec_total_MW", X=None, date_range=None,
                 samples=None, percentile=96, refresh=False, **_):
        FakeTotal.calls.append(dict(Y=Y, samples=samples, percentile=percentile,
                                    n=None if date_range is None else len(date_range)))
        ref = synthetic_total(2018)
        if samples is None:
            super().__init__(ref)
            return
        X = list(X or self.EXOGENOUS_VARIABLES[Y])
        years = sorted(set(date_range.year))
        weather = pd.concat([synthetic_total(y, seed=y).loc[:, X] for y in years]).loc[date_range]
        base = pd.concat([synthetic_total(y, seed=y)[Y] for y in years]).loc[date_range] * 1.02
        data = weather.copy()
        if samples > 1 and percentile is None:
            for n in range(samples):
                data[f"sample_{n}"] = base + n
            cols = [c for c in data if c.startswith("sample_")]
        else:
            data[Y] = base
            cols = [Y]
        data.iloc[:3, [data.columns.get_loc(c) for c in cols]] = np.nan
        data.iloc[-3:, [data.columns.get_loc(c) for c in cols]] = np.nan
        super().__init__(data.rename_axis("timestamp"))

    @classmethod
    def _clear_cache(cls):
        cls.cache = {}


@pytest.fixture(autouse=True)
def fake_total(monkeypatch):
    FakeTotal.calls = []
    monkeypatch.setattr(loads, "Total", FakeTotal)
    yield FakeTotal


def test_series_modes_and_edges():
    p = fetch.series("Alameda CA", 2020)
    assert len(p) == 8784 and p["elec_total_MW"].notna().all()
    assert p.attrs["loadskill"]["edge_hours_filled"] == 6
    assert FakeTotal.calls[-1]["samples"] == 0
    n = fetch.series("Alameda CA", 2020, edges="nan")
    assert n["elec_total_MW"].isna().sum() == 6
    s = fetch.series("Alameda CA", 2020, mode="samples", samples=3)
    assert [c for c in s if c.startswith("sample_")] == ["sample_0", "sample_1", "sample_2"]
    assert FakeTotal.calls[-1]["percentile"] is None
    q = fetch.series("Alameda CA", 2020, mode="percentile", samples=10, percentile=95)
    assert FakeTotal.calls[-1] == {"Y": "elec_total_MW", "samples": 10, "percentile": 95, "n": 8784}
    assert q.attrs["loadskill"]["percentile"] == 95


def test_series_pad_requests_wider_range():
    out = fetch.series("Alameda CA", hourly_2019 := pd.date_range(
        "2019-06-01", "2019-06-30 23:00", freq="1h", tz="UTC"), edges="pad")
    assert FakeTotal.calls[-1]["n"] == len(hourly_2019) + 6
    assert len(out) == len(hourly_2019) and out["elec_total_MW"].notna().all()


def test_series_rejects_flat_sector_without_X():
    with pytest.raises(ValueError, match="flat"):
        fetch.series("Alameda CA", 2020, "elec_industrial_MW")
    with pytest.raises(ValueError):
        fetch.series("Alameda CA", 2020, mode="percentile", samples=1)


def test_dg_is_clipped():
    d = fetch.series("Alameda CA", 2020, "elec_dg_MW")
    assert (d["elec_dg_MW"] <= 0).all()


def test_county_loads_sectors_sum_and_actuals():
    df = fetch.county_loads("Alameda CA", [2018, 2020], sectors=True)
    rep = validate(df, require_full_years=True)
    assert rep.ok, str(rep)
    assert len(df) == 8760 + 8784
    assert np.allclose(df.loc["2020", "elec_industrial_MW"], 223.618)
    ref = synthetic_total(2018)
    assert np.allclose(df.loc["2018", "elec_total_MW"], ref["elec_total_MW"])
    assert "hours replaced by 2018 training data" in " ".join(df.attrs["loadskill"]["notes"])
    # 2018 and 2020 are predicted as separate blocks, never bridged
    assert sum(1 for c in FakeTotal.calls if c["n"] == 8784) >= 3


def test_county_loads_direct():
    df = fetch.county_loads("Alameda CA", 2021, use_training_actuals=False)
    assert {"elec_total_MW", "elec_dg_MW", "elec_net_MW"} <= set(df)
    assert validate(df).ok


def test_batch_collects_errors():
    res = fetch.batch(["Alameda CA", "Kern CA"], fetch.series, 2019)
    assert set(res.frames) == {"Alameda CA", "Kern CA"} and not res.errors
    panel = res.column("elec_total_MW")
    assert panel.shape == (8760, 2)

    def boom(c, *a, **k):
        raise RuntimeError("no data")

    res = fetch.batch(["Alameda CA"], boom)
    assert res.errors == {"Alameda CA": "RuntimeError: no data"}


def test_county_loads_eia_dg(monkeypatch):
    import loads.dgen

    class FakeDG(pd.DataFrame):
        def __init__(self, state, county, date_range=None, refresh=False, **_):
            super().__init__({"elec_dg_MW": -5.0}, index=date_range)

    monkeypatch.setattr(loads.dgen, "DG", FakeDG)
    df = fetch.county_loads("Alameda CA", [2018, 2020], dg_source="eia")
    assert (df["elec_dg_MW"] == -5.0).all()  # EIA DG kept in 2018 hours, not replaced by stock PV
    assert np.allclose(df["elec_net_MW"], df["elec_total_MW"] - 5.0)
    assert df.attrs["loadskill"]["mode"].endswith("dg_source=eia)")
    assert not any(c["Y"] == "elec_dg_MW" for c in FakeTotal.calls)  # no TSGAM DG model fitted
    with pytest.raises(ValueError, match="dg_source"):
        fetch.county_loads("Alameda CA", 2020, dg_source="dgen")
