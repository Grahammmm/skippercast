"""NB-SC-12: ocean.wcofs() on one recorded, unedited WCOFS reply (tests/fixtures/recorded/wcofs, sidecar
has URL, time, sha256). Catalog/.dds/.das/axis replies are scaffolding that only place the recorded window
at the indices its URL names."""
from datetime import datetime, timezone
import hashlib, json, unittest
from urllib.parse import urlsplit
from skippercast.pipeline.ocean import dap_arrays, wcofs
from tests._support import ROOT

DIR = ROOT / 'tests/fixtures/recorded/wcofs'
BODY = (DIR / '20261101.ascii').read_bytes()
TEXT = BODY.decode('ascii')
SIDECAR = json.loads((DIR / '20261101.json').read_text())
NAME = 'wcofs.t03z.20261101.regulargrid.f018.nc'
NOW = datetime(2026, 11, 1, 22, tzinfo=timezone.utc)
REGION = {'bounds': [-121.20, 35.08, -120.64, 35.64]}  # selects rows 417..430, columns 605..618 below
FILL = -99999.0


def axis(name, at_index, value, n):
    return f'{name}[{n}][1]\n' + ', '.join(str(round(value + (i - at_index) * 0.04, 6)) for i in range(n)) + '\n'


def units_line(units):
    return '' if units is None else f'String units "{units}";'


class Client:
    def __init__(self, frame, uv_units='m s-1', v_units=...):
        self.frame, self.urls, self.requests = frame, [], []
        self.u_units, self.v_units = uv_units, uv_units if v_units is ... else v_units

    def get(self, url):
        self.urls.append(url)
        if url.endswith('catalog.xml'):
            return f'<dataset name="{NAME}" urlPath="NOAA/WCOFS/MODELS/2026/11/01/{NAME}"/>'
        if url.endswith('.dds'):
            return 'Dataset { Float64 Latitude[ny = 440][nx = 640]; } x;'
        if url.endswith('.das'):
            return ('time { String units "seconds since 2016-01-01 00:00:00"; }\n'
                    f'u_eastward {{ {units_line(self.u_units)} }}\nv_northward {{ {units_line(self.v_units)} }}')
        if 'Depth' in url:
            return ('Dataset { } x;\n' + '-' * 45 + '\n' + axis('Latitude', 417, 35.1, 440)
                    + axis('Longitude', 605, -121.18, 640) + 'Depth[1]\n0.0\n')
        if url != SIDECAR['url']:
            raise AssertionError('wcofs() did not send the recorded request: ' + url)
        return self.frame


def run(frame=TEXT, **kw):
    client = Client(frame, **kw)
    return wcofs(client, REGION, NOW), client


def section(text, name, change):
    """Apply change() to one variable's block of the DAP ASCII body, in memory only."""
    head, rest = text.split('\n' + name + '[', 1)
    block, tail = rest.split('\n\n', 1)
    return head + '\n' + name + '[' + change(block) + '\n\n' + tail


class RecordedWcofsTests(unittest.TestCase):
    def test_recorded_body_parses_to_wet_cells_in_knots_at_the_cycle_valid_time(self):
        out, client = run()
        self.assertEqual(client.urls[-1], SIDECAR['url'])
        arrays = dap_arrays(TEXT)
        self.assertEqual({k: len(v) for k, v in arrays.items()},
                         {'Latitude': 196, 'Longitude': 196, 'mask': 196, 'time': 1, 'u_eastward': 196, 'v_northward': 196})
        wet = sum(1 for m in arrays['mask'] if m == 1)
        self.assertEqual(wet, 112)
        [frame] = out['frames']
        self.assertEqual(frame['source_file'], NAME)
        self.assertEqual(len(frame['cells']), wet)  # every wet cell is published; the 0/975 class fails here
        valid = int(datetime(2026, 11, 1, 21, tzinfo=timezone.utc).timestamp())
        self.assertEqual((frame['time'], out['valid_from'], out['valid_through']), (valid, valid, valid))
        self.assertTrue(all(35.1 <= c[0] <= 35.62 and -121.18 <= c[1] <= -120.66 for c in frame['cells']))
        self.assertTrue(all(0 < c[2] < 2 and 0 <= c[3] < 360 for c in frame['cells']))  # m/s read, knots out
        cell = next(c for c in frame['cells'] if c[:2] == [35.34, -120.9])
        self.assertAlmostEqual(cell[2], 0.088, places=3)
        self.assertAlmostEqual(cell[3], 123.4, places=1)

    def test_sidecar_sha256_and_size_match_the_body(self):
        self.assertEqual(hashlib.sha256(BODY).hexdigest(), SIDECAR['sha256'])
        self.assertEqual(len(BODY), SIDECAR['bytes'])
        self.assertLessEqual(len(BODY), 20 * 1024)
        tampered = BODY.replace(b'0.037846133', b'0.037846134')
        self.assertNotEqual(hashlib.sha256(tampered).hexdigest(), SIDECAR['sha256'])
        sources = json.loads((ROOT / 'catalog/sources.json').read_text())['sources']
        hosts = next(s['allowed_hosts'] for s in sources if s['id'] == 'noaa-wcofs')
        self.assertIn(urlsplit(SIDECAR['url']).hostname, hosts)

    def test_recorded_fill_value_is_dropped_never_published_as_zero(self):
        arrays = dap_arrays(TEXT)
        self.assertEqual(arrays['u_eastward'].count(FILL), 196 - 112)  # the parser keeps the fill, not 0
        all_wet = section(TEXT, 'mask', lambda block: block.replace('0.0', '1.0'))
        self.assertEqual(sum(dap_arrays(all_wet)['mask']), 196)
        [frame] = run(all_wet)[0]['frames']
        self.assertEqual(len(frame['cells']), 112)  # fill cells stay absent even when the mask says wet
        self.assertNotIn([35.18, -120.74], [c[:2] for c in frame['cells']])  # a recorded fill cell
        self.assertTrue(all(c[2] > 0 for c in frame['cells']))

    def test_uv_units_other_than_metres_per_second_raise_naming_the_variable(self):
        # NB-SC-11 row 1 (was pinned as a known gap): a unit change is refused, never published.
        baseline = run()[0]
        self.assertEqual(run(uv_units='meters second-1')[0]['frames'], baseline['frames'])  # same m/s, other spelling
        for units in ('cm s-1', 'knots', '', None, 'M S-1', ' m s-1'):
            with self.subTest(units=units), self.assertRaisesRegex(ValueError, r'^WCOFS units changed: u_eastward$'):
                run(uv_units=units)
        for units in ('cm s-1', None):
            with self.subTest(v_only=units), self.assertRaisesRegex(ValueError, r'^WCOFS units changed: v_northward$'):
                run(v_units=units)
        client = Client(TEXT, uv_units='cm s-1')
        with self.assertRaises(ValueError):
            wcofs(client, REGION, NOW)
        self.assertFalse(any(SIDECAR['url'] == u for u in client.urls))  # refused before any data read

    def test_cell_counts_report_valid_of_total_and_an_all_dry_cut_is_missing(self):
        from skippercast.pipeline.collect import source
        out = run()[0]
        self.assertEqual((out['valid_cells'], out['total_cells']), (112, 196))
        [frame] = out['frames']
        self.assertEqual((frame['valid_cells'], frame['total_cells']), (112, 196))
        self.assertEqual(set(frame), {'time', 'cells', 'source_file', 'valid_cells', 'total_cells'})
        all_dry = section(TEXT, 'mask', lambda block: block.replace('1.0', '0.0'))
        self.assertEqual(sum(dap_arrays(all_dry)['mask']), 0)
        dry = run(all_dry)[0]
        self.assertEqual((dry['valid_cells'], dry['total_cells'], dry['frames'][0]['cells']), (0, 196, []))
        def via_collect(frame):
            return source('wcofs', 'NOAA WCOFS surface currents', 'forecast', 'https://tidesandcurrents.noaa.gov/',
                          36, lambda c: wcofs(c, REGION, NOW), NOW, client_factory=lambda now: Client(frame))
        self.assertEqual(via_collect(TEXT)['status'], 'ok')
        missing = via_collect(all_dry)
        self.assertEqual((missing['status'], missing['issue']),
                         ('missing', 'No usable cells in this regional grid; no gap filling applied'))

    def test_truncated_body_raises_instead_of_a_partial_frame(self):
        with self.assertRaises(KeyError):
            run(TEXT[:len(TEXT) // 2])
        with self.assertRaises(ValueError):
            run(TEXT[:int(len(TEXT) * 0.9)])
