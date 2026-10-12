"""Every configured station priority chain is backed by a reviewed catalog choice.

docs/operations/station-failover.md: a backup is added only after its
inventory, coordinates, exposure and endpoints are reviewed and recorded in
catalog/station-failover.json. This keeps a region from naming a backup that
nobody reviewed.
"""
import json
from unittest import TestCase

from tests._support import ROOT

CATALOG = json.loads((ROOT / "catalog" / "station-failover.json").read_text())


def chains(region):
    contexts = [c["stations"] for c in region.get("contexts", {}).values()]
    for stations in [region["stations"], *contexts]:
        for role, config in stations.get("roles", {}).items():
            yield role, config


class StationFailoverEvidenceTests(TestCase):
    def test_each_backup_has_a_reviewed_choice(self):
        # The first rollout's choices predate region and role fields; later ones name both.
        reviewed = {(c.get("region"), c.get("role"), c["primary"], c["backup"]) for c in CATALOG["choices"]}
        for path in sorted((ROOT / "regions").glob("*/region.json")):
            region = json.loads(path.read_text())
            for role, config in chains(region):
                with self.subTest(region=region["id"], role=role):
                    self.assertEqual(config.get("evidence"), "catalog/station-failover.json")
                    ids = config["stations"]
                    for backup in ids[1:]:
                        self.assertTrue({(region["id"], role, ids[0], backup), (None, None, ids[0], backup)} & reviewed,
                                        f"no reviewed choice for {ids[0]} -> {backup}")

    def test_morro_bay_offshore_falls_back_to_santa_maria_only(self):
        stations = json.loads((ROOT / "regions" / "morro-bay" / "region.json").read_text())["stations"]
        self.assertEqual(stations["roles"], {"offshore_buoy": {"stations": ["46028", "46011"],
                                                               "evidence": "catalog/station-failover.json"}})
        note = next(r for r in CATALOG["unconfigured_regions"] if r["id"] == "morro-bay")["reason"]
        for single in ("46215", "9412110"):
            self.assertIn(single, note)
