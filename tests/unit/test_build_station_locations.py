"""RF2320-2: build_station_locations checks every row before it writes anything (offline; fake opener)."""
import io
import json
import os

import pytest

from scripts import build_station_locations as bsl

COUNTY = ("export const slo={id:'slo',temperatureStationId:'46215',\n"
          " tideStation:{id:'9412110',name:'Port San Luis'},\n buoys:[{id:'46215',name:'Diablo'},{id:'46028',name:'CSM'}],\n};\n")
GOOD_NDBC = {"46215": 'lat="35.204" lon="-120.859" name="Diablo Canyon"',
             "46028": 'lat="35.77" lon="-121.903" name="Cape San Martin"',
             "46011": 'lat="34.956" lon="-121.019" name="Santa Maria"'}
GOOD_COOPS = [{"id": "9412110", "lat": 35.1689, "lng": -120.7542, "name": "Port San Luis", "type": "R"},
              {"id": "9411406", "lat": 34.4, "lng": -119.7, "name": "Santa Barbara", "type": "S"}]


def ndbc(rows=GOOD_NDBC, extra=""):
    body = "".join(f'<station id="{i}" {attrs}/>' for i, attrs in rows.items())
    return f'<?xml version="1.0"?><stations>{body}{extra}</stations>'.encode()


def coops(rows=GOOD_COOPS):
    return json.dumps({"stations": rows}).encode()


@pytest.fixture
def root(tmp_path):
    for name, region in {"a": {"stations": {"tide": "9412110", "offshore_buoy": "46011"}},
                         "b": {"contexts": {"x": {"stations": {"roles": {"nearshore_buoy": {"stations": ["46028"]}}}}}}}.items():
        (tmp_path / "regions" / name).mkdir(parents=True)
        (tmp_path / "regions" / name / "region.json").write_text(json.dumps(region))
    (tmp_path / "packages/coast/src").mkdir(parents=True)
    (tmp_path / "packages/coast/src/counties.ts").write_text(COUNTY)
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog/station-locations.json").write_text('{"old": true}\n')
    return tmp_path


class Opener:
    def __init__(self, ndbc_body=None, coops_body=None, fail=None):
        self.bodies, self.fail, self.calls = {"ndbc": ndbc_body or ndbc(), "coops": coops_body or coops()}, fail, []

    def __call__(self, url, timeout):
        provider = "ndbc" if "ndbc" in url else "coops"
        self.calls.append(provider)
        if self.fail == provider:
            raise OSError("network down")
        return io.BytesIO(self.bodies[provider])


def run(root, opener, capsys):
    try:
        return bsl.main(root=root, opener=opener) or 0, capsys.readouterr().err
    except SystemExit as refused:  # a str code is printed by Python as one stderr line with exit status 1
        assert isinstance(refused.code, str) and capsys.readouterr().err == ""
        return 1, refused.code + "\n"


def files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and "regions" not in p.parts
                  and "packages" not in p.parts)


def assert_untouched(root):
    assert files(root) == ["catalog/station-locations.json"]
    assert (root / "catalog/station-locations.json").read_bytes() == b'{"old": true}\n'


def test_good_inventories_write_both_receipts_and_exactly_the_wanted_catalog(root, capsys):
    opener = Opener()
    code, err = run(root, opener, capsys)
    assert (code, err) == (0, "")
    catalog = json.loads((root / "catalog/station-locations.json").read_text())
    assert list(catalog["stations"]) == ["ndbc:46011", "ndbc:46028", "ndbc:46215", "coops:9412110"]
    assert catalog["stations"]["ndbc:46215"]["latitude"] == 35.204
    assert catalog["stations"]["coops:9412110"]["longitude"] == -120.7542
    assert list(catalog["sources"]) == ["ndbc", "coops"]
    assert (root / "var/station-locations/ndbc.xml").read_bytes() == opener.bodies["ndbc"]
    assert (root / "var/station-locations/coops.json").read_bytes() == opener.bodies["coops"]
    assert files(root) == ["catalog/station-locations.json", "var/station-locations/coops.json",
                           "var/station-locations/ndbc.xml"]
    first = (root / "catalog/station-locations.json").read_bytes()
    assert run(root, Opener(), capsys)[0] == 0  # same inputs, same bytes apart from retrieval time
    assert json.loads(first)["stations"] == json.loads((root / "catalog/station-locations.json").read_bytes())["stations"]


@pytest.mark.parametrize("field, value, named", [
    ("lat", "nan", "ndbc:46215: lat 'nan'"), ("lat", "N/A", "ndbc:46215: lat 'N/A'"),
    ("lon", "200", "ndbc:46215: lon '200'"), ("lat", "inf", "ndbc:46215: lat 'inf'"),
])
def test_bad_ndbc_coordinate_is_named_and_nothing_is_written(root, capsys, field, value, named):
    rows = dict(GOOD_NDBC, **{"46215": GOOD_NDBC["46215"].replace(f'{field}="', f'{field}="{value}" x{field}="')})
    code, err = run(root, Opener(ndbc_body=ndbc(rows)), capsys)
    assert code == 1 and err.startswith("build_station_locations: ") and named in err and err.count("\n") == 1
    assert_untouched(root)


def test_missing_and_duplicate_rows_and_bad_names_are_all_named_in_one_run(root, capsys):
    rows = {k: v for k, v in GOOD_NDBC.items() if k != "46011"}
    bad_coops = [dict(GOOD_COOPS[0], name=" "), dict(GOOD_COOPS[0], name="dup")]
    code, err = run(root, Opener(ndbc_body=ndbc(rows, extra='<station id="46028" lat="1" lon="1" name="x"/>'),
                                 coops_body=coops(bad_coops)), capsys)
    assert code == 1
    assert "ndbc:46011: expected one inventory row, got 0" in err
    assert "ndbc:46028: expected one inventory row, got 2" in err
    assert "coops:9412110: expected one inventory row, got 2" in err and "(3 errors)" in err
    assert_untouched(root)
    code, err = run(root, Opener(coops_body=coops([{k: v for k, v in GOOD_COOPS[0].items() if k != "name"}])), capsys)
    assert code == 1 and "coops:9412110: name missing or empty (1 error)" in err
    assert_untouched(root)


@pytest.mark.parametrize("bodies, named", [
    ({"coops_body": b'{"stationList": []}'}, "coops: inventory has no stations list"),
    ({"coops_body": b'{"stations": '}, "coops: unreadable inventory"),
    ({"coops_body": b'[1, 2]'}, "coops: inventory has no stations list"),
    ({"ndbc_body": b"<not xml"}, "ndbc: unreadable inventory"),
    ({"coops_body": coops([dict(GOOD_COOPS[0], lat=True)])}, "coops:9412110: lat 'True'"),
    ({"coops_body": coops([dict(GOOD_COOPS[0], lng=None)])}, "coops:9412110: lng 'None'"),
])
def test_unreadable_inventories_are_named(root, capsys, bodies, named):
    code, err = run(root, Opener(**bodies), capsys)
    assert code == 1 and named in err
    assert_untouched(root)


def test_coops_fetch_failure_after_ndbc_success_writes_nothing(root, capsys):
    opener = Opener(fail="coops")
    code, err = run(root, opener, capsys)
    assert opener.calls == ["ndbc", "coops"]
    assert (code, err) == (1, "build_station_locations: coops: fetch failed (OSError) (1 error)\n")
    assert "https://" not in err
    assert_untouched(root)


@pytest.mark.parametrize("text, named", [
    ("{broken", "regions/x/region.json: unreadable JSON"),
    ("[]", "regions/x/region.json: not a JSON object"),
    ('{"stations": {"tide": 9412110}}', "regions/x/region.json: tide station id is not a string"),
    ('{"stations": {"roles": {"offshore_buoy": {"stations": [46011]}}}}',
     "regions/x/region.json: offshore_buoy station id is not a string"),
    ('{"stations": {"tide": 0}}', "regions/x/region.json: tide station id is not a string"),
    ('{"stations": {"nearshore_buoy": false}}', "regions/x/region.json: nearshore_buoy station id is not a string"),
    ('{"stations": {"roles": {"offshore_buoy": {"stations": [[]]}}}}', "regions/x/region.json: offshore_buoy station id is not a string"),
])
def test_broken_region_is_named_before_any_fetch(root, capsys, text, named):
    (root / "regions/x").mkdir()
    (root / "regions/x/region.json").write_text(text)
    opener = Opener()
    code, err = run(root, opener, capsys)
    assert (code, err, opener.calls) == (1, f"build_station_locations: {named}\n", [])
    assert_untouched(root)


def test_failed_catalog_replace_keeps_old_catalog_and_leaves_no_temp(root, capsys, monkeypatch):
    real = os.replace

    def replace(src, dst):
        if str(dst).endswith("catalog/station-locations.json"):
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(bsl.os, "replace", replace)
    code, err = run(root, Opener(), capsys)
    assert (code, err) == (1, "build_station_locations: catalog/station-locations.json: write failed (OSError)\n")
    assert (root / "catalog/station-locations.json").read_bytes() == b'{"old": true}\n'
    assert sorted(p.name for p in (root / "catalog").iterdir()) == ["station-locations.json"]
    assert not [p for p in (root / "var").rglob(".*")]
