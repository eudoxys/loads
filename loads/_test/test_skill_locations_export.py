import json

import numpy as np
import pytest

from loads.skill import counties, read_csv, resolve, to_csv, to_long, to_player
from loads.skill.cli import main


@pytest.mark.parametrize("text", ["Alameda CA", "Alameda County, CA", "alameda county ca", "06001"])
def test_resolve_forms(text):
    c = resolve(text)
    assert (c.state, c.county, c.fips) == ("CA", "Alameda", "06001")
    assert c.county_st == "Alameda CA" and c.kwargs == {"state": "CA", "county": "Alameda"}
    assert c.system == "WECC" and c.tzoffset == -8.0


def test_resolve_tuple_and_accents():
    assert resolve("CA", "Los Angeles County").county == "Los Angeles"
    assert resolve(("NM", "dona ana")).county == "Doña Ana"
    assert resolve("East Baton Rouge Parish, LA").county == "East Baton Rouge"


def test_resolve_errors():
    with pytest.raises(KeyError, match="close matches"):
        resolve("Alamda CA")
    with pytest.raises(KeyError):
        resolve("Alameda ZZ")
    with pytest.raises(ValueError):
        resolve("Alameda")


def test_counties_filters():
    wecc = counties(system="WECC")
    assert len(wecc) > 300 and all(c.system == "WECC" for c in wecc)
    assert {c.state for c in counties(state="ca")} == {"CA"}


def test_csv_roundtrip_with_provenance(tmp_path, total2018):
    df = total2018.copy()
    df.attrs["loadskill"] = {"county": "Alameda CA", "mode": "training"}
    path = to_csv(df, str(tmp_path / "out" / "a.csv.gz"))
    back = read_csv(path)
    assert str(back.index.tz) == "UTC" and len(back) == 8760
    assert np.allclose(back["elec_total_MW"], df["elec_total_MW"].round(3))
    assert back.attrs["loadskill"]["mode"] == "training"
    assert back.attrs["loadskill"]["units"]["elec_total_MW"] == "MW"


def test_player_and_long(tmp_path, total2018):
    p = to_player(total2018["elec_net_MW"].iloc[:3], str(tmp_path / "net.player"), scale=1e3)
    lines = open(p).read().splitlines()
    assert lines[0].startswith("2018-01-01 00:00:00 UTC,")
    assert len(to_long(total2018[["elec_total_MW", "elec_dg_MW"]].iloc[:2])) == 4


def test_cli_validate_and_summarize(tmp_path, total2018, capsys):
    path = to_csv(total2018, str(tmp_path / "t.csv"))
    assert main(["validate", path, "--full-years"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert main(["summarize", path, "--column", "elec_net_MW"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["energy_MWh"]) == 12
    assert main(["resolve", "Maricopa County, AZ"]) == 0
    assert json.loads(capsys.readouterr().out)["county_st"] == "Maricopa AZ"
