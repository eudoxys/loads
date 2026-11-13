"""Exercise `loadskill.fetch` against stand-ins for `loads.Total` and `loads.Estimator`.

The stand-ins reproduce the output contracts read from `loads/total.py` and
`loads/estimator.py`: `Total` returns the 2018 sector columns and their sum
only; `Estimator("County ST",years,config=...)` returns the
`config.weather` columns and `config.enduse` for every hour of `years`
(gaps between years filled, then dropped), with the first 3 hours of the
first year NaN (weather lags) and 2018 kept as actuals when
`config.keep_actuals`. Real-data runs are in tests marked `network`.
"""

import numpy as np
import pandas as pd
import pytest

import loads
import loads.estimator
from loads.skill import fetch, schema, validate
from skill_synthetic import synthetic_total


class FakeTotal(pd.DataFrame):
    SECTORS = loads.Total.SECTORS

    def __init__(self, state, county, *, fuel="elec", refresh=False):
        super().__init__(synthetic_total(2018)[list(schema.TOTAL_COLUMNS)])


class FakeEstimator(pd.DataFrame):
    calls = []

    def __init__(self, county_st, years=None, *, config=None):
        config = config or loads.estimator.EstimatorConfig()
        FakeEstimator.calls.append(dict(county_st=county_st, years=list(years), sectors=list(config.sectors),
                                        enduse=config.enduse, weather=list(config.weather),
                                        keep_actuals=config.keep_actuals))
        span = range(min(years), max(years) + 1)
        frames = [synthetic_total(y, seed=y) for y in span]
        data = pd.concat(frames)
        columns = {"residential": "elec_residential_MW", "commercial": "elec_commercial_MW",
                   "industrial": "elec_industrial_MW", "agricultural": "elec_agricultural_MW"}
        Y = data[[columns[s] for s in config.sectors]].sum(axis=1) * 1.02
        Y.iloc[:3] = np.nan
        out = data[list(config.weather)].copy()
        out[config.enduse] = Y
        if 2018 in years and config.keep_actuals:
            ref = synthetic_total(2018)
            out.loc[ref.index, config.enduse] = ref[[columns[s] for s in config.sectors]].sum(axis=1)
        super().__init__(out[out.index.year.isin(years)])


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    FakeEstimator.calls = []
    monkeypatch.setattr(loads, "Total", FakeTotal)
    monkeypatch.setattr(loads.estimator, "Estimator", FakeEstimator)
    yield FakeEstimator


def test_training_is_sector_sum_only():
    t = fetch.training("Alameda CA")
    assert list(t.columns) == list(schema.TOTAL_COLUMNS)
    assert len(t) == 8760


def test_series_predict_and_edges():
    p = fetch.series("Alameda CA", 2020)
    assert len(p) == 8784 and p["elec_total_MW"].notna().all()
    assert list(p.columns) == list(schema.ESTIMATOR_WEATHER) + ["elec_total_MW"]
    assert p.attrs["loadskill"]["edge_hours_filled"] == 3
    assert FakeEstimator.calls[-1]["county_st"] == "Alameda CA"
    assert FakeEstimator.calls[-1]["years"] == [2020]
    n = fetch.series("Alameda CA", 2020, edges="nan")
    assert n["elec_total_MW"].isna().sum() == 3
    assert fetch.series("Alameda CA", 2020, mode="training").attrs["loadskill"]["mode"] == "training"
    with pytest.raises(ValueError, match="mode"):
        fetch.series("Alameda CA", 2020, mode="samples")


def test_series_maps_columns_to_estimator_config():
    r = fetch.series("Alameda CA", 2020, "elec_residential_MW")
    assert "elec_residential_MW" in r.columns and "elec_total_MW" not in r.columns
    assert FakeEstimator.calls[-1]["sectors"] == ["residential"]
    assert FakeEstimator.calls[-1]["enduse"] == "elec_total_MW"


def test_series_pad_estimates_previous_year():
    june = pd.date_range("2019-06-01", "2019-06-30 23:00", freq="1h", tz="UTC")
    fetch.series("Alameda CA", june, edges="pad")
    assert FakeEstimator.calls[-1]["years"] == [2019]  # mid-year start needs no padding
    out = fetch.series("Alameda CA", 2019, edges="pad")
    assert FakeEstimator.calls[-1]["years"] == [2018, 2019]
    assert len(out) == 8760 and out["elec_total_MW"].notna().all()


def test_series_rejects_flat_sectors_and_dg():
    with pytest.raises(ValueError, match="flat"):
        fetch.series("Alameda CA", 2020, "elec_industrial_MW")
    with pytest.raises(ValueError, match="DG"):
        fetch.series("Alameda CA", 2020, "elec_dg_MW")


def test_county_loads_sectors_sum_and_actuals():
    df = fetch.county_loads("Alameda CA", [2018, 2020], sectors=True)
    rep = validate(df, require_full_years=True)
    assert rep.ok, str(rep)
    assert len(df) == 8760 + 8784
    assert "elec_dg_MW" not in df and "elec_net_MW" not in df
    assert np.allclose(df.loc["2020", "elec_industrial_MW"], 223.618)
    ref = synthetic_total(2018)
    assert np.allclose(df.loc["2018", "elec_total_MW"], ref["elec_total_MW"])
    assert "hours replaced by 2018 training data" in " ".join(df.attrs["loadskill"]["notes"])


def test_county_loads_direct():
    df = fetch.county_loads("Alameda CA", 2021, use_training_actuals=False)
    assert {"elec_total_MW", "temperature_degF"} <= set(df)
    assert FakeEstimator.calls[-1]["keep_actuals"] is False
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
    df = fetch.county_loads("Alameda CA", [2018, 2020], dg=True)
    assert (df["elec_dg_MW"] == -5.0).all()  # EIA DG in every hour, 2018 included
    assert np.allclose(df["elec_net_MW"], df["elec_total_MW"] - 5.0)
    assert df.attrs["loadskill"]["mode"].endswith("dg=eia)")
    assert validate(df).ok
