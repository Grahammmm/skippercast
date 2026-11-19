"""F33-07 fixture: discovery across a coast seam is separate from inventory.

Run ``python -m tests.unit.test_f33_07_audit`` for the read-only baseline
replay against the checkout's sharder. The contract assertion may fail there;
required pytest runs only the valid reference control until SCA-453 is built.
"""

from collections import Counter

import pytest

pytestmark = pytest.mark.gis


def coast_fixture():
    from shapely.geometry import box, mapping

    # Invented bands that meet at y=0. The crossing polygon's centroid is north.
    bands = {"central": (-4, 0), "north": (0, 4)}
    coasts = {"regions": [{"id": coast, "latitude": limits} for coast, limits in bands.items()]}
    extents = {coast: box(-4, lo, 4, hi) for coast, (lo, hi) in bands.items()}

    def feature(ident, geometry):
        return {"type": "Feature", "properties": {"id": ident}, "geometry": mapping(geometry)}

    cross = feature("cross", box(0, -1, 2, 3))
    single = feature("single", box(-2, -3, -1, -2))
    data = {"type": "FeatureCollection", "scope": "generalized-statewide-usgs-hard-bottom-context",
            "features": [cross, single]}
    owners = {"central": [single], "north": [cross]}
    # Hand-authored pieces: area 2 central, area 6 north, one canonical ID.
    views = {"central": [feature("cross", box(0, -1, 2, 0)), single],
             "north": [feature("cross", box(0, 0, 2, 3))]}
    return data, coasts, extents, owners, views


def assert_coast_contract(data, extents, inventory, candidates):
    from shapely.geometry import shape

    assert Counter(row["properties"]["id"] for rows in inventory.values() for row in rows) == {
        "cross": 1, "single": 1,
    }
    views = {}
    for coast, extent in extents.items():
        # Model a consumer restricted to its own shard; clipping cannot find a missing row.
        pieces = [(row["properties"]["id"], shape(row["geometry"]).intersection(extent))
                  for row in candidates[coast]]
        visible = [(ident, geometry) for ident, geometry in pieces if geometry.area > 0]
        assert Counter(ident for ident, _ in visible) == (
            {"cross": 1, "single": 1} if coast == "central" else {"cross": 1}
        ), f"{coast}: regional discovery must include each intersecting feature once"
        views[coast] = dict(visible)

    cross, single = [shape(row["geometry"]) for row in data["features"]]
    central, north = (views[coast]["cross"] for coast in ("central", "north"))
    assert (central.area, north.area) == (2, 6)
    assert central.union(north).equals(cross)
    assert central.intersection(north).area == 0
    assert views["central"]["single"].equals(single)


def test_cross_boundary_discovery_preserves_canonical_inventory():
    data, _, extents, owners, views = coast_fixture()
    assert_coast_contract(data, extents, owners, views)


def replay_baseline():
    from research.scripts.split_usgs_context import split

    data, coasts, extents, _, _ = coast_fixture()
    shards = {coast: shard["features"] for coast, shard in split(data, coasts).items()}
    print("Shard sizes:", {coast: len(rows) for coast, rows in shards.items()}, flush=True)
    assert_coast_contract(data, extents, shards, shards)


if __name__ == "__main__":
    replay_baseline()
