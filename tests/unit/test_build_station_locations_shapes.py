"""RF0550-6: misshaped station blocks and an unreadable counties.ts are named before any fetch (offline)."""
import json

import pytest

from scripts import build_station_locations as bsl
from tests.unit.test_build_station_locations import Opener, assert_untouched, root, run  # noqa: F401  (root is a fixture)

REL = "regions/x/region.json"


class NeverOpen:
    def __call__(self, url, timeout):
        raise AssertionError(f"fetched {url} although the region was refused")


def write_region(root, region):
    (root / "regions/x").mkdir()
    (root / "regions/x/region.json").write_text(json.dumps(region))


def refused(root, capsys):
    code, err = run(root, NeverOpen(), capsys)
    assert code == 1 and err.count("\n") == 1 and err.startswith("build_station_locations: ")
    assert_untouched(root)
    return err


def test_valid_region_with_contexts_and_roles_wants_exactly_the_same_sets(root):
    write_region(root, {"stations": {"tide": "9411406", "roles": {"offshore_buoy": {"stations": ["46054"]}}},
                        "contexts": {"south": {"stations": {"nearshore_buoy": "46218",
                                                            "roles": {"tide": {"stations": ["9410840"]}}}},
                                     "bad key!": {"stations": {"roles": {"nearshore_buoy": {"stations": ["46053", ""]}}}}}})
    assert bsl.configured(root) == {"ndbc": {"46011", "46028", "46215", "46054", "46218", "46053"},
                                    "coops": {"9412110", "9411406", "9410840"}}


@pytest.mark.parametrize("region, named", [
    ({"contexts": []}, "contexts is not an object"),
    ({"contexts": None}, "contexts is not an object"),
    ({"contexts": {"south": "x"}}, "contexts.south is not an object"),
    ({"stations": "46011"}, "stations is not an object"),
    ({"stations": ["46011"]}, "stations is not an object"),
    ({"stations": {"roles": []}}, "stations.roles is not an object"),
    ({"stations": {"roles": {"tide": "9412110"}}}, "stations.roles.tide is not an object"),
    ({"stations": {"roles": {"offshore_buoy": {"stations": "46011"}}}}, "stations.roles.offshore_buoy.stations is not a list"),
    ({"stations": {"roles": {"nearshore_buoy": {"stations": {"id": "46011"}}}}},
     "stations.roles.nearshore_buoy.stations is not a list"),
    ({"contexts": {"south": {"stations": "46011"}}}, "contexts.south.stations is not an object"),
    ({"contexts": {"south": {"stations": {"roles": {"tide": {"stations": "9412110"}}}}}},
     "contexts.south.stations.roles.tide.stations is not a list"),
    ({"contexts": {"bad key!": {"stations": {"roles": "x"}}}}, "contexts.?.stations.roles is not an object"),
    ({"contexts": {"bad key!": 7}}, "contexts.? is not an object"),
    ({"contexts": {"k" * 41: {"stations": 1}}}, "contexts.?.stations is not an object"),
])
def test_misshaped_block_is_named_with_its_field_path_and_nothing_is_fetched(root, capsys, region, named):
    write_region(root, region)
    assert refused(root, capsys) == f"build_station_locations: {REL}: {named}\n"


def test_station_string_is_never_split_into_one_character_ids(root, capsys):
    write_region(root, {"stations": {"roles": {"offshore_buoy": {"stations": "46011"}}}})
    err = refused(root, capsys)
    assert "is not a list" in err and "expected one inventory row" not in err and "ndbc:4:" not in err


def test_null_stations_and_absent_roles_are_accepted_as_empty(root):
    for name, region in {"x": {"stations": None}, "y": {"stations": {"tide": "9411406"}},
                         "z": {"contexts": {"south": {"stations": {"roles": {"offshore_buoy": {}}}}, "north": {}}}}.items():
        (root / "regions" / name).mkdir()
        (root / "regions" / name / "region.json").write_text(json.dumps(region))
    assert bsl.configured(root) == {"ndbc": {"46011", "46028", "46215"}, "coops": {"9412110", "9411406"}}


@pytest.mark.parametrize("damage", ["missing", "not utf-8", "directory"])
def test_unreadable_counties_ts_is_named_exit_1_and_nothing_written(root, capsys, damage):
    county = root / "packages/coast/src/counties.ts"
    county.unlink()
    if damage == "not utf-8":
        county.write_bytes(b"\xff")
    elif damage == "directory":
        county.mkdir()
    err = refused(root, capsys)
    assert err == "build_station_locations: packages/coast/src/counties.ts: unreadable\n"
    assert not (root / "var").exists()


def test_valid_regions_still_build_the_catalog(root, capsys):
    write_region(root, {"stations": None, "contexts": {"south": {"stations": {"roles": {"tide": {"stations": []}}}}}})
    code, err = run(root, Opener(), capsys)
    assert (code, err) == (0, "")
    catalog = json.loads((root / "catalog/station-locations.json").read_text())
    assert sorted(catalog["stations"]) == ["coops:9412110", "ndbc:46011", "ndbc:46028", "ndbc:46215"]
