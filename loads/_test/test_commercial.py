"""Offline commercial aggregation tests; no credentials or downloads required."""
import importlib
import json
from pathlib import Path

import pandas as pd
import pytest

HERE = Path(__file__).parent
m = importlib.import_module("loads.commercial")


@pytest.fixture
def inputs(monkeypatch,tmp_path):
    monkeypatch.setattr(m,"States",lambda: pd.DataFrame({"ST":["CA"]}))
    monkeypatch.setattr(m,"Counties",lambda: pd.DataFrame({"ST":["CA"],"COUNTY":["Test"]}))
    monkeypatch.setattr(m.Commercial,"CACHEDIR",str(tmp_path))
    # Keep the actual cache implementation, but restore its global after the test.
    monkeypatch.setattr(m.Cache,"CACHEDIR",str(tmp_path))
    records = {"A":(100_000.,100_000.,1.),"B":(900_000.,900_000.,1.)}

    def configure(values,inventory=None,shift_type=None):
        def stock(**kwargs):
            building_type = kwargs["building_type"]
            represented,area,intensity = values[building_type]
            areas = represented if isinstance(represented,list) else [represented]
            watts = [intensity]*len(areas)
            columns = {c for group in m.Commercial.COLLECT.values() for c in group}
            columns.add("generation")
            data = {c:[0.]*len(areas) for c in columns}
            data["elec_equipment"] = watts
            data["generation"] = [-0.2 * value for value in watts]
            data["floor_area"] = areas
            start = "2018-01-02" if building_type == shift_type else "2018-01-01"
            return pd.DataFrame(data,index=pd.date_range(start,periods=len(areas),freq="1h",tz="UTC"))
        stock.BUILDING_TYPES = dict.fromkeys(values)
        monkeypatch.setattr(m,"COMstock",stock)
        if inventory is None:
            inventory = pd.DataFrame({"BUILDING_TYPE":list(values),
                "FLOORAREA":[r[1] for r in values.values()]})
        monkeypatch.setattr(m,"Floorarea",lambda **kwargs: inventory)
    configure(records)
    return configure,records


def test_uniform_intensity_preserves_total_county_area(inputs):
    result = m.Commercial("CA","Test")
    assert result.elec_total_MW.iloc[0] == pytest.approx(1.)
    assert result.elec_net_MW.iloc[0] == pytest.approx(1.)
    assert len(result.columns) == 10


def test_stock_mix_replaces_inventory_proportions(inputs):
    configure,_ = inputs
    inventory = pd.DataFrame({"BUILDING_TYPE":["A+B"],"FLOORAREA":[1_000_000.]})
    configure({"A":(100.,0.,1.),"B":(900.,0.,3.)},inventory)
    assert m.Commercial("CA","Test").elec_total_MW.iloc[0] == pytest.approx(2.8)
    inventory = pd.DataFrame({"BUILDING_TYPE":["A","B"],"FLOORAREA":[900_000.,100_000.]})
    configure({"A":(100.,0.,1.),"B":(900.,0.,3.)},inventory)
    assert m.Commercial("CA","Test",refresh=True).elec_total_MW.iloc[0] == pytest.approx(2.8)


def test_group_count_does_not_change_scale_and_cache_is_distinct(inputs):
    baseline = m.Commercial("CA","Test")
    groups = dict(m.Commercial.COLLECT,extra=["elec_equipment"])
    result = m.Commercial("CA","Test",collect=groups)
    assert result.elec_total_MW.equals(baseline.elec_total_MW)
    assert result.extra_MW.iloc[0] == pytest.approx(1.)


def test_common_metadata_multiplier_cancels(inputs):
    configure,records = inputs
    records = {"A":(100_000.,100_000.,1.),"B":(900_000.,900_000.,3.)}
    configure(records)
    expected = m.Commercial("CA","Test")
    configure({k:(4*s,area,intensity) for k,(s,area,intensity) in records.items()})
    actual = m.Commercial("CA","Test",refresh=True)
    pd.testing.assert_frame_equal(pd.DataFrame(actual),pd.DataFrame(expected))


def test_time_varying_stock_shares(inputs):
    configure,_ = inputs
    configure({"A":([100_000.,900_000.],100_000.,1.),
        "B":([900_000.,100_000.],900_000.,3.)})
    assert m.Commercial("CA","Test").elec_total_MW.tolist() == pytest.approx([2.8,1.2])


def test_zero_total_stock_area_raises_instead_of_nan(inputs):
    configure,_ = inputs
    configure({"A":([100_000.,0.],100_000.,0.),"B":([900_000.,0.],900_000.,0.)})
    with pytest.raises(ValueError,match="No represented commercial floor area"):
        m.Commercial("CA","Test")


def test_custom_empty_group_is_honored(inputs):
    groups = dict(m.Commercial.COLLECT,elec_baseload=[])
    result = m.Commercial("CA","Test",collect=groups)
    assert result.elec_baseload_MW.iloc[0] == 0.
    assert result.elec_total_MW.iloc[0] == 0.


def test_legacy_cache_is_not_reused(inputs,tmp_path):
    cache = tmp_path / "loads/0/CA/Test/C.csv.gz"
    cache.parent.mkdir(parents=True)
    pd.DataFrame({"elec_total_MW":[999.]},index=pd.date_range("2018-01-01",periods=1,tz="UTC")).to_csv(cache)
    before = cache.read_bytes()
    assert m.Commercial("CA","Test").elec_total_MW.iloc[0] == 1.
    assert cache.read_bytes() == before


def test_independent_load_solar_calibration_preserves_net_and_cache(inputs,monkeypatch):
    groups = dict(m.Commercial.COLLECT,elec_dg=["generation"])
    first = m.Commercial("CA","Test",collect=groups,calibrate={"load":2.,"solar":3.})
    assert first.elec_total_MW.iloc[0] == pytest.approx(2.)
    assert first.elec_dg_MW.iloc[0] == pytest.approx(-0.6)
    assert first.elec_net_MW.iloc[0] == pytest.approx(1.4)
    monkeypatch.setattr(m,"_build_loads",lambda *args: pytest.fail("Cache was not reused"))
    cached = m.Commercial("CA","Test",collect=groups)
    assert cached.elec_total_MW.iloc[0] == pytest.approx(1.)
    assert cached.elec_dg_MW.iloc[0] == pytest.approx(-0.2)
    assert cached.elec_net_MW.iloc[0] == pytest.approx(0.8)


def test_misaligned_profiles_raise(inputs):
    configure,records = inputs
    configure(records,shift_type="B")
    with pytest.raises(ValueError,match="timestamps differ"):
        m.Commercial("CA","Test")


def test_unmapped_inventory_is_included_in_county_total(inputs):
    configure,records = inputs
    inventory = pd.DataFrame({"BUILDING_TYPE":["A","CMS"],"FLOORAREA":[100_000.,900_000.]})
    configure(records,inventory)
    result = m.Commercial("CA","Test")
    assert result.elec_total_MW.iloc[0] == pytest.approx(1.)


def test_real_la_hour(inputs):
    configure,_ = inputs
    fixture = json.loads((HERE / "fixtures/commercial_la_first_hour.json").read_text())
    records = {r["type"]:(4*r["represented_area_ft2"],0.,
        1000*sum(r["quarter_hour_electricity_kWh"])/r["represented_area_ft2"]) for r in fixture["records"]}
    inventory = pd.DataFrame({"BUILDING_TYPE":["ALL"],
        "FLOORAREA":[fixture["county_inventory_area_ft2"]]})
    configure(records,inventory)
    result = m.Commercial("CA","Test").elec_total_MW.iloc[0]
    assert result == pytest.approx(fixture["expected_elec_total_MW"],rel=0,abs=0.0001)
