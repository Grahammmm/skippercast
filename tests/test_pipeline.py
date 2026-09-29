from datetime import datetime, timezone
from pathlib import Path
import unittest
import ssl
from skippercast import http
from skippercast.pipeline import parsers
from skippercast.pipeline import coastal_watch, collect
from skippercast.pipeline.collect import Client, source, validate
from skippercast.pipeline.settings import settings
from tests import http_fixture

PORTS = settings('morro-bay')['report_ports']
NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class PipelineTests(unittest.TestCase):
    def test_certificate_failure_fails_closed_without_a_curl_fallback(self):
        # The former /usr/bin/curl fallback is gone: a certificate that does not verify
        # fails the source (retained/failed upstream), is not retried, and says how to fix it.
        url = 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Sport-Fishing/General-Ocean-Fishing-Regs'
        failure = ssl.SSLCertVerificationError(1, 'certificate verify failed')
        failure.verify_message = 'unable to get local issuer certificate'
        session, script, sleeps = http_fixture.session(failure, failure)
        client = Client(NOW, session=session)
        with self.assertRaises(http.TLSVerificationError) as raised:
            client.get(url)
        self.assertIn('trust store', str(raised.exception))
        self.assertEqual(len(script.requests), 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(client.requests[-1]['error_class'], 'TLSVerificationError')
        self.assertNotIn('transport', client.requests[-1])
        for module in (collect, coastal_watch):
            self.assertNotIn('/usr/bin/curl', Path(module.__file__).read_text())

    def test_coastwatch_403_is_retried_but_other_hosts_stay_denied(self):
        url = 'https://coastwatch.pfeg.noaa.gov/erddap/info/jplMURSST41/index.json'
        session, script, sleeps = http_fixture.session((403, b'transient provider denial'),
                                                       (200, b'{"table": {"rows": []}}'))
        client = Client(NOW, session=session)
        self.assertEqual(client.get(url, as_json=True)['table']['rows'], [])
        self.assertEqual(len(script.requests), 2)
        self.assertEqual([r.get('http_status') for r in client.requests], [403, 200])
        self.assertEqual([r['attempt'] for r in client.requests], [1, 2])
        self.assertEqual(len(sleeps), 1)

        session, script, _ = http_fixture.session((403, b'denied'), (200, b'{}'))
        with self.assertRaises(http.HTTPStatusError) as raised:
            Client(NOW, session=session).get('https://www.ndbc.noaa.gov/data/realtime2/46028.txt')
        self.assertEqual(raised.exception.status, 403)
        self.assertEqual(len(script.requests), 1)

    def test_server_errors_are_retried_then_recorded_per_attempt(self):
        url = 'https://www.ndbc.noaa.gov/data/realtime2/46028.txt'
        session, script, _ = http_fixture.session((503, b'busy'), (503, b'busy'))
        client = Client(NOW, session=session)
        with self.assertRaises(http.HTTPStatusError):
            client.get(url)
        self.assertEqual(len(script.requests), 2)  # two attempts, as before
        self.assertEqual([(r['attempt'], r['http_status']) for r in client.requests], [(1, 503), (2, 503)])
        self.assertTrue(all(r['error'].startswith('HTTPStatusError') for r in client.requests))

    def test_successful_receipt_keeps_the_published_fields(self):
        url = 'https://www.ndbc.noaa.gov/data/realtime2/46028.txt'
        headers = {'Date': 'Thu, 24 Sep 2026 12:00:00 GMT', 'Content-Type': 'text/plain',
                   'Last-Modified': 'Thu, 24 Sep 2026 11:50:00 GMT'}
        session, script, _ = http_fixture.session((200, b'#YY MM DD\n', headers))
        client = Client(NOW, session=session)
        client.get(url)
        record = client.requests[-1]
        for key in ('url', 'attempt', 'retrieved_at', 'http_status', 'http_date', 'final_url', 'content_type',
                    'last_modified', 'bytes', 'sha256'):
            self.assertIn(key, record)
        self.assertEqual((record['http_status'], record['final_url'], record['bytes']), (200, url, 10))
        self.assertEqual(script.requests[0]['headers']['User-Agent'], http.USER_AGENT)
        self.assertEqual(script.requests[0]['headers']['Accept-Encoding'], 'gzip')

    def test_private_and_unlisted_hosts_fail_closed_and_are_recorded(self):
        def private(host, port, **_):
            return [(2, 1, 6, '', ('10.0.0.8', port))]
        session, script, _ = http_fixture.session((200, b'secret'), resolver=private)
        client = Client(NOW, session=session)
        with self.assertRaisesRegex(ValueError, 'non-public'):
            client.get('https://www.ndbc.noaa.gov/data/realtime2/46028.txt')
        with self.assertRaisesRegex(ValueError, 'allowlist'):
            client.get('https://unreviewed.example.org/data')
        self.assertEqual(script.requests, [])
        self.assertEqual([r['error_class'] for r in client.requests], ['DisallowedHost', 'DisallowedHost'])
        result = source('x', 'X', 'observation', 'https://unreviewed.example.org/data', 6,
                        lambda c: c.get('https://unreviewed.example.org/data'), NOW,
                        client_factory=lambda now: Client(now, session=session))
        self.assertEqual(result['status'], 'failed')
        self.assertIn('DisallowedHost', result['issue'])

    def test_trip_counts_preserve_release_zero_and_unknown_location(self):
        page = '''Fish Counts September 20, 2026
        <tr><td><a href="/boats/test"><b>Example Boat</b></a>Morro Bay, CA</td>
        <td>12 Anglers<br>3/4 Day<br><i>Out Front</i></td>
        <td>1,200 Rockfish, 3 Lingcod (up to 9 pounds), 2 Lingcod Released, 0 Halibut</td>
        <tr><td><a href="/boats/other"><b>Other Boat</b></a>Avila Beach, CA</td>
        <td>3 Anglers<br>1/2 Day AM<br><i>Pecho Rock</i></td><td>4 Red Rockcod</td>'''
        result = parsers.charter_reports(page, "2026-09-20", "https://www.socalfishreports.com/example", ports=PORTS)
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
                parsers.charter_reports(page, "2026-09-20", "https://example.org", ports=PORTS)

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
        sample = {"predictions": [{"t": "2026-09-22 01:00", "v": "4.2", "type": "H"}]}
        r = parsers.tides(sample, "9412110", "Port San Luis reference. Not Morro Bay bar current or slack-water predictions.")
        self.assertEqual(r["datum"], "MLLW")
        self.assertEqual(r["predictions"][0]["time"], "2026-09-22T01:00:00Z")
        self.assertIn("Not Morro Bay", r["note"])
        monterey = parsers.tides(sample, "9413450", "Monterey tide reference; no Big Sur current prediction.")
        self.assertEqual(monterey["station"], "9413450")
        self.assertIn("Big Sur", monterey["note"])
        with self.assertRaises(ValueError):
            parsers.tides({"error": {"message": "outage"}}, "9413450", "Monterey reference")

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
