"""Readers of the precomputed WECC files in `loads/wecc/` (`loads.skill.wecc`)

No network. Tests that read the precomputed estimates are skipped when
those files are not installed (non-editable install); the DG reader must
work either way, because `county_dg.csv.gz` is package data.
"""

import os

import numpy as np
import pytest

import loads
from loads.skill import validate, wecc_dg, wecc_estimate
from loads.skill import wecc
from loads.skill.cli import main

_WECC = os.path.join(os.path.dirname(loads.__file__), "wecc")
needs_repo_data = pytest.mark.skipif(
    not all(os.path.exists(os.path.join(_WECC, f))
            for f in ("wecc_estimate.csv.gz", "county_dg_scaled.csv.gz")),
    reason="loads/wecc estimate files are not installed (non-editable install)",
)


@needs_repo_data
def test_wecc_estimate_columns_and_index():
    df = wecc_estimate(["Alameda County, CA", "Washoe NV"], 2020)
    assert list(df.columns) == ["Alameda CA", "Washoe NV"]
    assert len(df) == 8784 and str(df.index.tz) == "UTC" and df.index.name == "timestamp"
    assert df.notna().all().all() and (df > 0).all().all()
    assert validate(df.rename(columns={"Alameda CA": "elec_total_MW"})[["elec_total_MW"]],
                    require_full_years=True).ok
    assert df.attrs["loadskill"]["mode"] == "wecc_estimate"
    with pytest.raises(KeyError):
        wecc_estimate("Cook IL", 2020)  # not WECC


@needs_repo_data
def test_wecc_dg_conventions():
    load = wecc_dg(["Alameda CA", "Kern CA"], 2020)
    assert (load <= 0).all().all() and load["Alameda CA"].min() < 0
    assert (load["Kern CA"] == 0).all()  # not in county_dg.csv.gz
    assert any("Kern CA" in n for n in load.attrs["loadskill"]["notes"])
    out = wecc_dg("Kern CA", 2020, scaled=True, convention="output")
    assert out["Kern CA"].max() > 0
    assert len(load) == 8784 and load.notna().all().all()  # first 7 UTC hours of 2018 not in file


@needs_repo_data
def test_estimate_minus_dg_is_retail_energy():
    # wecc_estimate.py calibrates monthly energy to county_mwh.csv + county_dg.csv.gz
    import pandas as pd
    gross = wecc_estimate("Maricopa AZ", 2021)["Maricopa AZ"]
    dg = wecc_dg("Maricopa AZ", 2021)["Maricopa AZ"]
    retail = pd.read_csv(wecc.path("county_mwh.csv"), index_col=0)["Maricopa AZ"]
    retail.index = pd.to_datetime(retail.index, format="%b %Y").tz_localize("UTC")
    monthly = (gross + dg).resample("MS").sum()
    assert np.allclose(monthly, retail.reindex(monthly.index), rtol=1e-3)


@needs_repo_data
def test_cli_wecc(tmp_path, capsys):
    path = str(tmp_path / "w.csv")
    assert main(["wecc", "Alameda CA", "--years", "2019", "-o", path]) == 0
    assert '"rows": 8760' in capsys.readouterr().out


def test_wecc_dg_needs_only_installed_files(monkeypatch):
    # county_dg.csv.gz is package data: wecc_dg must not need wecc_estimate.csv.gz
    real = wecc.path
    def path(name):
        if name in ("estimate", "nodes", "dg_scaled"):
            raise FileNotFoundError(name)
        return real(name)
    monkeypatch.setattr(wecc, "path", path)
    dg = wecc_dg(["Alameda CA", "Kern CA"], 2020)
    assert dg["Alameda CA"].min() < 0 and (dg["Kern CA"] == 0).all()
    with pytest.raises(KeyError, match="not a WECC county"):
        wecc_dg("Cook IL", 2020)
