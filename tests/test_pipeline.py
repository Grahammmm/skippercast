from datetime import datetime, timezone
import unittest
from unittest.mock import patch
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from skippercast.pipeline import parsers
from skippercast.pipeline.collect import Client, source, system_tls_official_watch, validate


class PipelineTests(unittest.TestCase):
    def test_cdfw_system_tls_fallback_is_exact_url_only(self):
        with self.assertRaisesRegex(ValueError, 'exact reviewed watch'):
            system_tls_official_watch('https://wildlife.ca.gov/unreviewed', 100)
        with self.assertRaisesRegex(ValueError, 'restricted to reviewed state agencies'):
            system_tls_official_watch('https://example.org/unreviewed', 100)

    def test_cdfw_certificate_failure_uses_verified_fallback(self):
        url = 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Sport-Fishing/General-Ocean-Fishing-Regs'
        class Opener:
            def open(self, *_args, **_kwargs):
                raise URLError(ssl.SSLCertVerificationError('untrusted local Python certificate chain'))
        with patch('skippercast.pipeline.collect.check_public_address'), \
                patch('skippercast.pipeline.collect.build_opener', return_value=Opener()), \
                patch('skippercast.pipeline.collect.system_tls_official_watch',
                      return_value=(b'<html>official page</html>', {'content-type': 'text/html'})) as fallback:
            client = Client(datetime(2026, 9, 24, tzinfo=timezone.utc))
            self.assertIn('official page', client.get(url))
        fallback.assert_called_once_with(url, 5_000_000)
        self.assertEqual(client.requests[-1]['transport'], 'system curl; TLS verified; redirects disabled')

    def test_system_tls_fallback_rejects_an_official_redirect(self):
        url = 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Sport-Fishing/General-Ocean-Fishing-Regs'
        def redirect(args, **_kwargs):
            self.assertNotIn('--location', args)
            Path(args[args.index('--dump-header') + 1]).write_text(
                'HTTP/2 301\r\nLocation: https://wildlife.ca.gov/other\r\n\r\n')
            Path(args[args.index('--output') + 1]).write_bytes(b'redirect')
        with patch('skippercast.pipeline.collect.subprocess.run', side_effect=redirect):
            with self.assertRaisesRegex(ValueError, 'redirected'):
                system_tls_official_watch(url, 5_000_000)

    def test_coastwatch_403_is_retried_but_other_hosts_stay_denied(self):
        class Response:
            status = 200
            headers = {}
            url = 'https://coastwatch.pfeg.noaa.gov/erddap/info/jplMURSST41/index.json'

            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, _): return b'{"table": {"rows": []}}'

        class Opener:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                if self.calls == 1:
                    raise HTTPError(request.full_url, 403, 'transient provider denial', {}, None)
                return Response()

        opener = Opener()
        with patch('skippercast.pipeline.collect.check_public_address'), \
                patch('skippercast.pipeline.collect.build_opener', return_value=opener), \
                patch('skippercast.pipeline.collect.time.sleep'):
            client = Client(datetime(2026, 9, 24, tzinfo=timezone.utc))
            self.assertEqual(client.get(Response.url, as_json=True)['table']['rows'], [])
        self.assertEqual(opener.calls, 2)
        self.assertEqual([r.get('http_status') for r in client.requests], [403, 200])

        opener = Opener()
        with patch('skippercast.pipeline.collect.check_public_address'), \
                patch('skippercast.pipeline.collect.build_opener', return_value=opener), \
                patch('skippercast.pipeline.collect.time.sleep'):
            with self.assertRaises(HTTPError):
                Client(datetime(2026, 9, 24, tzinfo=timezone.utc)).get('https://example.org/data')
        self.assertEqual(opener.calls, 1)

    def test_trip_counts_preserve_release_zero_and_unknown_location(self):
        page = '''Fish Counts September 20, 2026
        <tr><td><a href="/boats/test"><b>Example Boat</b></a>Morro Bay, CA</td>
        <td>12 Anglers<br>3/4 Day<br><i>Out Front</i></td>
        <td>1,200 Rockfish, 3 Lingcod (up to 9 pounds), 2 Lingcod Released, 0 Halibut</td>
        <tr><td><a href="/boats/other"><b>Other Boat</b></a>Avila Beach, CA</td>
        <td>3 Anglers<br>1/2 Day AM<br><i>Pecho Rock</i></td><td>4 Red Rockcod</td>'''
        result = parsers.charter_reports(page, "2026-09-20", "https://www.socalfishreports.com/example")
        a, b = result["reports"]
        self.assertEqual(a["anglers"], 12)
        self.assertEqual(a["catches"][0]["count"], 1200)
        self.assertEqual(a["catches"][2]["disposition"], "released")
        self.assertNotIn("halibut", a["species"])
        self.assertEqual(a["catches"][3]["count"], 0)
        self.assertIsNone(a["ground_id"])
        self.assertIsNone(a["coordinates"])
        self.assertIsNone(a["fishing_hours"])
        self.assertEqual(b["ground_id"], "CHARTER-PECHO")
        self.assertNotIn("sample_at", result)

    def test_report_errors_do_not_become_zero_catch(self):
        for page in ("Access denied", "Fish Counts September 19, 2026"):
            with self.assertRaises(ValueError):
                parsers.charter_reports(page, "2026-09-20", "https://example.org")

    def test_ndbc_missing_fields_and_units(self):
        page = '#YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP\n#yr mo dy hr mn degT m/s m/s m sec sec degT hPa degC degC\n2026 09 21 15 56 99 MM MM 1.0 17 6.2 207 MM MM 16.9\n'
        result = parsers.ndbc(page, "46215")
        self.assertEqual(result["sample_at"], "2026-09-21T15:56:00Z")
        self.assertIsNone(result["observations"][0]["WSPD"])
        self.assertEqual(result["observations"][0]["WDIR"], 99)
        with self.assertRaises(ValueError):
            parsers.ndbc(page.replace('m/s', 'kn'), "46215")

    def test_failure_keeps_original_data_dates(self):
        now = datetime(2026, 9, 21, tzinfo=timezone.utc)
        previous = {"data": {"sample_at": "2026-09-19T00:00:00Z"},
                    "last_success_at": "2026-09-19T01:00:00Z", "data_retrieved_at": "2026-09-19T01:00:00Z"}
        def fail(c):
            raise ValueError("test outage")
        r = source("a", "A", "observation", "https://example.org", 6, fail, now, previous)
        self.assertEqual(r["status"], "retained")
        self.assertEqual(r["data_retrieved_at"], previous["data_retrieved_at"])
        self.assertEqual(r["data"], previous["data"])
        r = source("a", "A", "observation", "https://example.org", 6, lambda c: previous["data"], now)
        self.assertEqual(r["status"], "stale")

    def test_erddap_axis_orientation_missing_cells_and_quality(self):
        meta = {"attrs": {"NC_GLOBAL": {"time_coverage_end": "2026-09-20T12:00:00Z"},
                          "chlorophyll": {"valid_min": "0.001", "valid_max": "100"}},
                "dimensions": {"time": "", "latitude": "averageSpacing=-0.04", "longitude": "averageSpacing=0.04"},
                "variables": {"chlorophyll": ["time", "latitude", "longitude"]}}
        q = parsers.erddap_query(meta, ["chlorophyll"], {"latitude": [35, 36], "longitude": [-122, -120]}, 1)
        self.assertIn('[(36):1:(35)]', q)
        grid = {"table": {"columnNames": ["time", "latitude", "longitude", "chlorophyll"],
                           "columnUnits": ["UTC", "degrees_north", "degrees_east", "mg m-3"],
                           "rows": [["2026-09-20T12:00:00Z", 35.3, -121.5, None],
                                    ["2026-09-20T12:00:00Z", 35.4, -121.5, 2.3]]}}
        r = parsers.erddap_grid(grid, meta, ["chlorophyll"], "chlorophyll")
        self.assertEqual(r["valid_cells"], 1)
        self.assertIsNone(r["samples"][0]["chlorophyll"])
        grid["table"]["columnUnits"][-1] = 'other'
        with self.assertRaises(ValueError):
            parsers.erddap_grid(grid, meta, ["chlorophyll"], "chlorophyll")

    def test_tides_have_datum_and_never_imply_current(self):
        r = parsers.tides({"predictions": [{"t": "2026-09-22 01:00", "v": "4.2", "type": "H"}]})
        self.assertEqual(r["datum"], "MLLW")
        self.assertEqual(r["predictions"][0]["time"], "2026-09-22T01:00:00Z")
        self.assertIn("Not Morro Bay", r["note"])
        with self.assertRaises(ValueError):
            parsers.tides({"error": {"message": "outage"}})

    def test_zero_alerts_requires_recognized_response(self):
        self.assertEqual(parsers.alerts({"type": "FeatureCollection", "features": []})["alerts"], [])
        with self.assertRaises(ValueError):
            parsers.alerts({})

    def test_gate_rejects_fabricated_bite_probability(self):
        data = {"schema_version": 1, "generated_at": "2026-09-21T00:00:00Z", "sources": {}, "reports": [], "catch_probability": .8}
        with self.assertRaises(ValueError):
            validate(data)


if __name__ == "__main__":
    unittest.main()
