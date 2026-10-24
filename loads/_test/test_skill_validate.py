import numpy as np
import pandas as pd

from loads.skill import validate


def test_clean_frame_passes(total2018):
    rep = validate(total2018, require_full_years=True)
    assert rep.ok, str(rep)
    assert rep.rows == 8760


def test_leap_year_rows(total2020):
    assert len(total2020) == 8784
    assert validate(total2020, require_full_years=True).ok


def test_positive_dg_is_error(total2018):
    df = total2018.copy()
    df.iloc[100, df.columns.get_loc("elec_dg_MW")] = 5.0
    df["elec_net_MW"] = df["elec_total_MW"] + df["elec_dg_MW"]
    rep = validate(df)
    assert not rep.ok
    assert any(i.check == "dg-sign" for i in rep.errors())


def test_net_identity(total2018):
    df = total2018.copy()
    df["elec_net_MW"] = df["elec_total_MW"]  # the double-counting bug pattern
    rep = validate(df)
    assert any(i.check == "net-identity" for i in rep.errors())


def test_sector_sum(total2018):
    df = total2018.copy()
    df["elec_total_MW"] *= 1.01
    df["elec_net_MW"] = df["elec_total_MW"] + df["elec_dg_MW"]
    rep = validate(df)
    assert [i.check for i in rep.errors()] == ["sector-sum"]


def test_edge_nan_is_warning_interior_nan_is_error(total2018):
    df = total2018[["temperature_degF", "elec_total_MW"]].copy()
    df.iloc[:3, 1] = np.nan
    df.iloc[-3:, 1] = np.nan
    rep = validate(df)
    assert rep.ok and any(i.check == "edge-nan" for i in rep.issues)
    df.iloc[500, 1] = np.nan
    assert not validate(df).ok


def test_gap_naive_and_duplicates(total2018):
    gap = total2018.drop(total2018.index[10:12])
    assert any(i.check == "hourly" for i in validate(gap).errors())
    naive = total2018.tz_localize(None)
    assert any(i.check == "timezone" for i in validate(naive).errors())
    dup = pd.concat([total2018.iloc[:5], total2018.iloc[4:10]])
    assert any(i.check == "duplicates" for i in validate(dup).errors())


def test_raise_if_failed(total2018):
    df = total2018.copy()
    df["elec_dg_MW"] = 1.0
    try:
        validate(df).raise_if_failed()
    except ValueError as err:
        assert "dg-sign" in str(err)
    else:
        raise AssertionError("expected ValueError")
