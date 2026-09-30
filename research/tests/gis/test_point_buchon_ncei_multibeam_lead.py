import gzip
import hashlib
import json
import struct
import unittest

from research.scripts import audit_point_buchon_ncei_multibeam_lead as lead
from research.lib.receipts import RECEIPTS
from research.lib.paths import ROOT


class PointBuchonNCEILeadTest(unittest.TestCase):
    def test_public_receipt_is_only_an_acquisition_lead(self):
        result = json.loads((RECEIPTS / "point-buchon-2007-ncei-multibeam-lead.json").read_text())
        self.assertEqual(result["scope"], "point-buchon-2007-ncei-multibeam-acquisition-lead")
        self.assertEqual(result["qualified_waypoints"], 0)
        self.assertFalse(result["fishing_target"])
        self.assertFalse(result["exportable"])
        self.assertEqual({row["survey_id"] for row in result["surveys"]}, set(lead.SURVEYS))
        self.assertTrue(all(row["metadata_vertical_datum"] == "Unknown" for row in result["surveys"]))
        self.assertGreater(sum(row["nominal_usgs_200_300ft_hard_rugose_cell_centers_in_catalog_polygon"]
                               for row in result["surveys"]), 0)
        self.assertEqual(set(result["processed_gsf_probes"]), set(lead.SURVEYS))
        self.assertTrue(all(not row["datum_qualified"] for row in result["processed_gsf_probes"].values()))
        self.assertEqual(set(result["selected_line_navigation_swath_screens"]), set(lead.SURVEYS))
        self.assertEqual(set(result["selected_line_unknown_datum_depth_ranges"]), set(lead.SURVEYS))
        for row in result["selected_line_navigation_swath_screens"].values():
            self.assertFalse(row["actual_gsf_beam_to_usgs_cell_overlap_verified"])
            self.assertGreater(row["sampled_usgs_pixels_by_class"]["200_300ft_hard_rugose"], 0)
        self.assertTrue(all("TIDAL_DATUM=UNKNOWN" in row["processing_parameters"]
                            for row in result["processed_gsf_probes"].values()))

    def test_selected_line_companions_and_depth_bounds(self):
        url = lead.PROBES["PointBuchon"]["url"]
        inf, fnv = lead.companion_urls(url)
        self.assertTrue(inf.endswith("/generated/PB129-2245.gsf.mb121.inf"))
        self.assertTrue(fnv.endswith("/generated/PB129-2245.gsf.mb121.fnv"))
        raw = b"Minimum Depth: 78.64 Maximum Depth: 91.7086"
        found = lead.original_line_depth_range(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(found["minimum_depth_m_unknown_datum"], 78.64)
        with self.assertRaisesRegex(ValueError, "no longer spans"):
            changed = b"Minimum Depth: 100 Maximum Depth: 110"
            lead.original_line_depth_range(changed, hashlib.sha256(changed).hexdigest())

    def test_wrong_catalog_lineage_fails(self):
        features = []
        for name, spec in lead.SURVEYS.items():
            for oid in sorted(spec["ids"]):
                features.append({"attributes": {"OBJECTID": oid, "NCEI_ID": spec["ncei_id"],
                                                "SURVEY_ID": name, "SURVEY_YEAR": 2007},
                                 "geometry": {"rings": [[[-121, 35], [-120, 35], [-120, 36], [-121, 35]]]}})
        features[0]["attributes"]["NCEI_ID"] = "wrong"
        with self.assertRaisesRegex(ValueError, "lineage changed"):
            lead.catalog(lambda _url: json.dumps({"features": features}).encode())

    def test_archive_metadata_must_declare_datum_status(self):
        def fetcher(url):
            if "metaview" in url:
                return b"Vertical Datum: MLLW"
            return b'<a href="https://example.org/file.gsf.mb121.gz">processed</a>' * 60
        with self.assertRaisesRegex(ValueError, "archive listing or datum metadata"):
            lead.archive_page("PointBuchon", fetcher)

    def test_gsf_processing_record_exposes_unknown_tidal_datum(self):
        def record(kind, body):
            return struct.pack(">II", len(body), kind) + body

        params = ["TIDE_COMPENSATED=YES", "GEOID=WGS-84", "TIDAL_DATUM=UNKNOWN"]
        body = struct.pack(">IIH", 1, 0, len(params))
        for value in params:
            encoded = value.encode()
            body += struct.pack(">H", len(encoded)) + encoded
        sample = record(1, b"GSF-v03.01\0\0") + record(4, body) + record(2, b"\0" * 56)
        compressed = gzip.compress(sample)
        parsed = lead.parse_gsf_probe(compressed, hashlib.sha256(compressed).hexdigest())
        self.assertEqual(parsed["swath_ping_records"], 1)
        self.assertFalse(parsed["datum_qualified"])
        changed = gzip.compress(sample.replace(b"TIDAL_DATUM=UNKNOWN", b"TIDAL_DATUM=MLLW\0\0\0"))
        with self.assertRaisesRegex(ValueError, "datum or tide-processing"):
            lead.parse_gsf_probe(changed, hashlib.sha256(changed).hexdigest())


if __name__ == "__main__":
    unittest.main()
