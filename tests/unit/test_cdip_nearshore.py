"""FE-40: CDIP nearshore model collector, offline against an excerpt of CDIP's published SL345 forecast."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import tempfile
from unittest import TestCase
from unittest.mock import patch

from skippercast.http import FakeSession, TransportError
from skippercast.pipeline import cdip_nearshore as cdip
from skippercast.platform.contracts import load_catalogs, load_region
from tests._support import FIXTURES, ROOT
from tests.unit.test_ndbc_history import TsTypes, split_top

FIX = FIXTURES / "cdip"
DAS = (FIX / "SL345.das").read_text()
ASCII = (FIX / "SL345.ascii").read_text()
NOW = datetime(2026, 10, 8, 16, tzinfo=timezone.utc)  # the excerpt was issued 2026-10-08T13:47:44Z
FETCHED = "2026-10-08T16:01:00.000Z"
BINDING = {"id": "SL345", "name": "Morro Rock", "areaId": "central", "lat": 35.36503, "lon": -120.87659}
PISMO = {"id": "SL097", "name": "Pismo Beach Pier", "areaId": "south", "lat": 35.13593, "lon": -120.6609}
# The five reviewed SLO sites in fish `enrichmentBindings.slo.nearshore` order.
FISH_SITES = [("SL097", "Pismo Beach Pier", "south", 35.13593, -120.6609),
              ("SL165", "Port San Luis", "south", 35.16219, -120.74368),
              ("SL345", "Morro Rock", "central", 35.36503, -120.87659),
              ("SL400", "Cayucos Pier", "central", 35.43385, -120.91185),
              ("SL552", "San Simeon Beach", "north", 35.58976, -121.13583)]


def parse(das=DAS, text=ASCII, binding=BINDING, now=NOW):
    return cdip.parse_site(das, text, binding, FETCHED, now)


def with_array(name, values, declared=None, text=ASCII):
    """The excerpt with one array's values (and optionally its declared length) replaced."""
    count = len(values) if declared is None else declared
    body = f"{name}[{count}]\n" + ", ".join(str(v) for v in values)
    replaced, n = re.subn(rf"{name}\[8\]\n[^\n]*", body, text)
    assert n == 1, name
    return replaced


def routes(*bindings):
    return {url: body.encode() for b in bindings if b["id"] == "SL345"
            for url, body in ((cdip.das_url("SL345"), DAS), (cdip.data_url("SL345"), ASCII))}


class CoastTypes(TsTypes):
    """`TsTypes` over packages/coast `types.ts` (SourceStatus) and `enrichment-types.ts` (NearshoreSite)."""

    def __init__(self):
        self.types = {}
        for name in ("types.ts", "enrichment-types.ts"):
            source = re.sub(r"\s*\n\s*", " ", (ROOT / "packages/coast/src" / name).read_text())
            for chunk in source.split("export type ")[1:]:
                ident, expr = chunk.split("=", 1)
                self.types[ident.strip()] = split_top(expr, ";")[0]


class ParseTests(TestCase):
    def test_published_excerpt_keeps_native_clocks_and_values(self):
        site = parse()
        self.assertEqual((site["issuedAt"], site["freshness"], site["fetchedAt"]),
                         ("2026-10-08T13:47:44.000Z", "current", FETCHED))
        # Window: three hours back, 72 ahead; the 12:00 sample is outside it.
        self.assertEqual([h["at"][11:16] for h in site["hours"]], ["15:00", "18:00", "21:00", "00:00", "03:00", "06:00", "09:00"])
        first = site["hours"][0]
        self.assertAlmostEqual(first["waveFt"], 1.0604185 * 3.280839895, 9)
        self.assertEqual((first["periodS"], first["directionDeg"], first["qualityFlag"], first["secondaryFlag"]),
                         (16.666668, 261.216, 1, 0))
        self.assertEqual((site["temporalResolutionMinutes"], site["waterDepthM"], site["validThrough"]),
                         (180, 14.99, "2026-10-09T09:00:00.000Z"))
        self.assertEqual((site["sourceId"], site["url"], site["kind"], site["availability"]),
                         ("cdip-SL345", "https://cdip.ucsd.edu/mops/?mop=SL345", "forecast", "available"))
        self.assertIn("not supplied", site["depthDatum"])
        self.assertIsNone(site["modelInputCycleAt"])

    def test_site_label_or_coordinate_mismatch_raises(self):
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            parse(text=ASCII.replace('"SL345"', '"SL346"'))
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            parse(binding={**BINDING, "id": "SL400"})
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            parse(text=ASCII.replace('metaSiteLabel, "SL345"\n', ""))
        for text in (ASCII.replace("metaLatitude, 35.36503", "metaLatitude, 35.39"),
                     ASCII.replace("metaLongitude, -120.87659", "metaLongitude, -120.85"),
                     ASCII.replace("metaLongitude, -120.87659\n", "")):
            with self.assertRaisesRegex(ValueError, "coordinates mismatch"):
                parse(text=text)
        with self.assertRaisesRegex(ValueError, "coordinates mismatch"):
            parse(binding={**BINDING, "lat": 35.40})

    def test_partial_arrays_are_rejected(self):
        heights = [1.0720557, 1.0604185, 1.05244, 1.0469304, 1.040345, 1.0325757, 1.0297607]
        with self.assertRaisesRegex(ValueError, "Incomplete CDIP array: waveHs"):
            parse(text=with_array("waveHs", heights, declared=8))  # seven values under an eight-value header
        with self.assertRaisesRegex(ValueError, "Incomplete CDIP array: waveTime"):
            parse(text=ASCII.replace("waveTime[8]", "waveTime[9]"))
        with self.assertRaisesRegex(ValueError, "Missing CDIP array: waveHs"):
            parse(text=with_array("waveHs", heights))  # complete itself, shorter than the time axis
        with self.assertRaisesRegex(ValueError, "Missing CDIP array: waveFlagSecondary"):
            parse(text=re.sub(r"waveFlagSecondary\[8\]\n[^\n]*\n\n", "", ASCII))
        with self.assertRaisesRegex(ValueError, "Invalid DAP ASCII"):
            parse(text=ASCII.split("-----")[0])  # cut before the data
        cut = ASCII[:ASCII.index("waveTp[8]") + 40]  # cut inside an array
        with self.assertRaisesRegex(ValueError, "Incomplete CDIP array: waveTp"):
            parse(text=cut)

    def test_quality_flags_fill_values_and_valid_range_mask_values(self):
        text = with_array("waveFlagPrimary", [1, 1, 4, 1, 1, 1, 1, 1])
        text = with_array("waveFlagSecondary", [0, 0, 0, 1, 2, 0, 0, 0], text=text)
        text = with_array("waveHs", [1, 1, 1, 1, 1, -999.99, 25.0, 1], text=text)
        text = with_array("waveDp", [270, 270, 270, 270, 270, 270, 270, 361.0], text=text)
        hours = {h["at"][11:16]: h for h in parse(text=text)["hours"]}
        values = lambda at: (hours[at]["waveFt"], hours[at]["periodS"], hours[at]["directionDeg"])
        self.assertEqual(values("18:00"), (None, None, None))  # primary flag 4 (bad)
        self.assertEqual(hours["18:00"]["qualityFlag"], 4)
        self.assertEqual(values("21:00"), (None, None, None))  # insufficient_input
        self.assertAlmostEqual(hours["00:00"]["waveFt"], 3.280839895)  # low_energy keeps height only
        self.assertEqual(values("00:00")[1:], (None, None))
        self.assertIsNone(hours["03:00"]["waveFt"])  # fill value
        self.assertIsNone(hours["06:00"]["waveFt"])  # above valid_max 20 m
        self.assertIsNone(hours["09:00"]["directionDeg"])  # above valid_max 360
        self.assertEqual(hours["09:00"]["periodS"], 14.285714)

    def test_contract_changes_raise(self):
        changes = {"units changed: waveHs": DAS.replace('String units "meter"', 'String units "foot"'),
                   "direction convention": DAS.replace("sea_surface_wave_from_direction", "sea_surface_wave_to_direction"),
                   "time origin": DAS.replace("seconds since 1970-01-01", "hours since 1970-01-01"),
                   "quality flag contract": DAS.replace("insufficient_input low_energy", "low_energy"),
                   "Missing CDIP metadata: NC_GLOBAL": DAS.replace("NC_GLOBAL", "GLOBAL")}
        for message, das in changes.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                parse(das=das)
        with self.assertRaisesRegex(ValueError, "not unique and increasing"):
            parse(text=ASCII.replace("1791460800, 1791471600", "1791471600, 1791471600"))

    def test_issue_clock_is_the_publishers_date_issued(self):
        missing = parse(das=re.sub(r"\n\s+String date_issued [^\n]*", "", DAS))
        self.assertEqual((missing["issuedAt"], missing["freshness"]), (None, "unknown"))  # date_created is never used
        stale = parse(das=DAS.replace('date_issued "2026-10-08T13:47:44Z"', 'date_issued "2026-10-06T13:00:00Z"'))
        self.assertEqual(stale["freshness"], "stale")
        self.assertEqual(parse(now=NOW - timedelta(hours=2, minutes=17))["freshness"], "current")  # 4 min skew
        with self.assertRaisesRegex(ValueError, "in the future"):
            parse(now=NOW - timedelta(hours=2, minutes=30))

    def test_window_without_good_heights_raises(self):
        with self.assertRaisesRegex(ValueError, "no samples in the report window"):
            parse(now=NOW + timedelta(days=4))
        with self.assertRaisesRegex(ValueError, "no good-quality wave heights"):
            parse(text=with_array("waveFlagPrimary", [3] * 8))


class OutputShapeTests(TestCase):
    def test_feed_records_match_packages_coast_types(self):
        feed = cdip.collect("morro-bay", [BINDING, PISMO], NOW, session=FakeSession(routes(BINDING)))
        types = CoastTypes()
        self.assertEqual(types.errors(feed["nearshore"], "NearshoreSite[]"), [])
        self.assertEqual(types.errors(feed["sources"], "SourceStatus[]"), [])
        self.assertEqual([s["availability"] for s in feed["nearshore"]], ["available", "error"])
        json.dumps(feed, allow_nan=False)
        # The checker catches wrong value types, literals and extra fields, not only field names.
        broken = json.loads(json.dumps(feed["nearshore"]))
        broken[0]["hours"][0]["waveFt"] = "3.5"
        broken[0]["kind"] = "observation"
        broken[0]["directionConvention"] = "toward"
        broken[1]["waterDepthFt"] = 3
        del broken[1]["fetchedAt"]
        self.assertEqual(len(types.errors(broken, "NearshoreSite[]")), 5)


class CollectTests(TestCase):
    def test_one_failing_site_does_not_block_the_others(self):
        session = FakeSession({**routes(BINDING), cdip.das_url("SL097"): (503, b"busy")})
        feed = cdip.collect("morro-bay", [PISMO, BINDING], NOW, session=session)
        pismo, morro = feed["nearshore"]
        self.assertEqual((morro["availability"], len(morro["hours"])), ("available", 7))
        self.assertEqual((pismo["availability"], pismo["hours"], pismo["issuedAt"], pismo["freshness"]),
                         ("error", [], None, "unknown"))
        self.assertIn("503", pismo["error"])
        self.assertEqual([s["outcome"] for s in feed["sources"]], ["error", "ok"])
        self.assertEqual(feed["sources"][1]["issuedAt"], "2026-10-08T13:47:44.000Z")
        self.assertEqual(feed["health"], {"status": "degraded", "issues": ["cdip-SL097"]})
        self.assertEqual((feed["region_id"], feed["generated_at"], feed["source_id"]), ("morro-bay", "2026-10-08T16:00:00Z", "cdip-mop"))
        self.assertIn("CDIP, Scripps Institution of Oceanography", feed["credit"])

    def test_reads_are_bounded_to_the_cdip_model_path(self):
        session = FakeSession(routes(BINDING))
        cdip.collect("morro-bay", [BINDING], NOW, session=session)
        self.assertEqual([url for _, url, _ in session.calls], [cdip.das_url("SL345"), cdip.data_url("SL345")])
        for _, url, options in session.calls:
            self.assertTrue(url.startswith("https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/model/MOP_alongshore/SL345_forecast.nc."))
            self.assertEqual((options["allowed_hosts"], options["allowed_prefixes"], options["max_bytes"], options["timeout"]),
                             (["thredds.cdip.ucsd.edu"], [cdip.BASE], 750_000, 12))

    def test_failed_site_keeps_a_recent_previous_record_unchanged(self):
        good = cdip.collect("morro-bay", [BINDING], NOW, session=FakeSession(routes(BINDING)))
        good["nearshore"][0]["fetchedAt"] = "2026-10-08T14:30:00.000Z"
        failing = FakeSession({cdip.das_url("SL345"): TransportError("reset")})
        kept = cdip.collect("morro-bay", [BINDING], NOW, good, session=failing)
        self.assertEqual(kept["nearshore"][0], good["nearshore"][0])
        self.assertIn("kept the previous record fetched 2026-10-08T14:30:00.000Z", kept["sources"][0]["error"])
        self.assertEqual(kept["health"]["status"], "degraded")
        # Three hours or more after its fetch, or from another region, it is not lent.
        good["nearshore"][0]["fetchedAt"] = "2026-10-08T13:00:00.000Z"
        self.assertEqual(cdip.collect("morro-bay", [BINDING], NOW, good, session=failing)["nearshore"][0]["availability"], "error")
        good["nearshore"][0]["fetchedAt"] = "2026-10-08T15:00:00.000Z"
        self.assertEqual(cdip.collect("cambria-san-simeon", [BINDING], NOW, good, session=failing)["nearshore"][0]["availability"], "error")


class BindingTests(TestCase):
    def test_committed_region_binds_the_five_reviewed_slo_sites(self):
        sites = cdip.bindings(load_region("morro-bay"), load_catalogs()[1])
        self.assertEqual([(s["id"], s["name"], s["areaId"], s["lat"], s["lon"]) for s in sites], FISH_SITES)
        self.assertEqual(cdip.bindings(load_region("cambria-san-simeon"), load_catalogs()[1]), [])

    def test_catalog_source_carries_the_cdip_credit(self):
        source = load_catalogs()[1]["cdip-mop"]
        self.assertEqual((source["adapter"], source["review_status"]), (cdip.ADAPTER, "candidate"))
        self.assertTrue(source["rights"]["attribution_required"])
        self.assertIn("CDIP, Scripps Institution of Oceanography", source["rights"]["attribution"])
        self.assertIn(cdip.HOST, source["allowed_hosts"])

    def test_invalid_site_configuration_raises(self):
        region, sources = load_region("morro-bay"), load_catalogs()[1]
        config = region["nearshore_model"]
        site = config["sites"][0]
        bad = {"Invalid or duplicate": [site, site], "outside the region": [{**site, "lat": 36.5}],
               "needs a name": [{**site, "area_id": "South Coast"}]}
        for message, sites in bad.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                cdip.bindings({**region, "nearshore_model": {**config, "sites": sites}}, sources)
        with self.assertRaisesRegex(ValueError, "reviewed CDIP catalog source"):
            cdip.bindings({**region, "nearshore_model": {**config, "source_id": "ndbc-history"}}, sources)
        with self.assertRaisesRegex(ValueError, "names no sites"):
            cdip.bindings({**region, "nearshore_model": {**config, "sites": []}}, sources)


class PublishTests(TestCase):
    def test_publish_writes_the_feed_beside_latest_and_lends_previous_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, previous_root = Path(tmp) / "live/regions/morro-bay", Path(tmp) / "published"
            feed = cdip.publish("morro-bay", target, previous_root, NOW, FakeSession(routes(BINDING)))
            written = json.loads((target / "nearshore.json").read_text())
            self.assertEqual(written["nearshore"], feed["nearshore"])
            self.assertEqual([s["id"] for s in written["nearshore"]], [s[0] for s in FISH_SITES])
            self.assertEqual(written["health"]["issues"], ["cdip-SL097", "cdip-SL165", "cdip-SL400", "cdip-SL552"])
            # Next cycle: SL345 fails and its record from this cycle is lent; a corrupt previous file is ignored.
            (previous_root / "regions/morro-bay").mkdir(parents=True)
            written["nearshore"][2]["fetchedAt"] = "2026-10-08T15:30:00.000Z"
            (previous_root / "regions/morro-bay/nearshore.json").write_text(json.dumps(written))
            again = cdip.publish("morro-bay", target, previous_root, NOW, FakeSession())
            self.assertEqual(again["nearshore"][2]["availability"], "available")
            (previous_root / "regions/morro-bay/nearshore.json").write_text("{")
            self.assertEqual(cdip.publish("morro-bay", target, previous_root, NOW, FakeSession())["nearshore"][2]["availability"], "error")
            self.assertIsNone(cdip.publish("cambria-san-simeon", Path(tmp) / "c", previous_root, NOW, FakeSession()))

    def test_cli_warns_and_never_fails_the_cycle(self):
        with tempfile.TemporaryDirectory() as tmp, patch("builtins.print") as printed, \
                patch.object(cdip, "publish", side_effect=ValueError("bad config")) as publish:
            self.assertEqual(cdip.main(["--output", tmp]), 0)
        self.assertEqual([call.args[0] for call in publish.call_args_list], ["morro-bay"])  # published regions binding sites
        self.assertIn("::warning title=Nearshore morro-bay not refreshed::ValueError: bad config", printed.call_args.args[0])
