"""End-to-end checks of the agent skill helpers on real data (Alameda CA)

Slow on first run: they download ResStock/ComStock, Census, OpenEI, NLR and
NSRDB data (including the national commercial floor-area and industrial and
agricultural inventories) and fit four TSGAM models. To keep CI cheap they
only run when `LOADS_TEST_SKILL=1` is set:

    LOADS_TEST_SKILL=1 pytest loads/_test/test_skill_network.py
"""

import os

import pytest

from loads.skill import configure, county_loads, series, summary, training, validate

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(os.environ.get("LOADS_TEST_SKILL") != "1",
                       reason="set LOADS_TEST_SKILL=1 to run the skill's end-to-end tests"),
]


@pytest.fixture(scope="module", autouse=True)
def env():
    return configure()


def test_training_frame_contract():
    df = training("Alameda CA")
    assert len(df) == 8760
    rep = validate(df, require_full_years=True)
    assert rep.ok, str(rep)


def test_predict_2020():
    df = series("Alameda CA", 2020)
    assert len(df) == 8784 and df["elec_total_MW"].notna().all()
    assert summary(df)["peak_MW"] > 0


def test_county_loads_2020_sectors():
    df = county_loads("Alameda CA", 2020, sectors=True)
    assert validate(df, require_full_years=True).ok
