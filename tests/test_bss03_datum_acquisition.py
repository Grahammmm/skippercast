"""Research diagnostics must not promote private camera blocks to fish marks."""
import io
import json
from pathlib import Path
import tarfile
import unittest

from scripts.audit_bss03_caris_acquisition import PREFIX_BYTES, URL, inspect, inspect_prefix
from scripts.audit_bss03_datum_footprint import compile_review, stable


ROOT = Path(__file__).resolve().parents[1]


class Bss03DatumAcquisitionTests(unittest.TestCase):
    def test_footprint_probe_stays_private_and_unqualified(self):
        blocks = json.loads((ROOT / 'var/review/bss03-camera-100m-blocks.geojson').read_text())
        access = json.loads((ROOT / 'dist/data/bss03-camera-access-triage.json').read_text())

        def get(params):
            return {'region': 'WESTCOAST', 's_h_frame': params['s_h_frame'],
                    's_v_frame': 'NAVD88', 's_v_geoid': 'geoid09', 's_v_unit': 'm',
                    't_h_frame': 'IGS14', 't_v_frame': 'MLLW', 't_v_unit': 'm',
                    's_x': params['s_x'], 's_y': params['s_y'],
                    't_x': params['s_x'], 't_y': params['s_y'],
                    't_z': '-0.02', 'uncertainty': '0.10'}

        report, private = compile_review(blocks, access, get=get)
        self.assertEqual(report['sample_count'], 15)
        self.assertEqual(len(private['samples']), 15)
        self.assertNotIn('longitude', json.dumps(report))
        self.assertNotIn('request_url', json.dumps(report))
        self.assertFalse(report['source_horizontal_realization_verified'])
        self.assertFalse(report['mllw_raster_converted'])
        self.assertFalse(report['upper_bounded_mllw_depth_verified'])
        self.assertEqual(report['qualified_waypoints'], 0)
        self.assertEqual(stable(report), stable(dict(report, checked_at='later')))
        with self.assertRaises(ValueError):
            compile_review(blocks, dict(access, private_block_fingerprint='changed'), get=get)

    def test_archive_head_is_lead_only(self):
        contents = {
            'BSS_Block03/BSS_Block03.hpf': b'PROJECTION = AUTO_UTM,WG84_10N\n',
            'BSS_Block03/45HaroldHeath_PPK/line/LogFile':
                (b'Uncertainty Source: Vessel Settings\nCompute TPU end:\n'
                 b'Tide Values:  Measured 0.000 (m), Zoning 0.000 (m)\n'),
            'BSS_Block03/45HaroldHeath_PPK/line/TPE': b'not a decoded surface',
        }
        compressed = io.BytesIO()
        with tarfile.open(fileobj=compressed, mode='w:gz') as archive:
            for name, data in contents.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        prefix = compressed.getvalue().ljust(PREFIX_BYTES, b'\0')
        head = lambda: {'status': 200, 'url': URL,
                        'content_length_bytes': '42090312342',
                        'last_modified': 'Fri, 10 May 2019 14:19:58 GMT',
                        'accept_ranges': 'bytes', 'content_type': 'application/x-gzip'}
        result = inspect(head, prefix=prefix)
        self.assertEqual(result['bounded_original_prefix']['project_projection'],
                         'AUTO_UTM,WG84_10N')
        self.assertFalse(result['bounded_original_prefix']['tpe_member_downloaded_or_decoded'])
        self.assertFalse(result['archive_contents_verified'])
        self.assertFalse(result['cube_or_tpu_surface_confirmed'])
        self.assertFalse(result['depth_qualified'])
        with self.assertRaises(ValueError):
            inspect(lambda: dict(head(), accept_ranges='none'), prefix=prefix)
        with self.assertRaises(ValueError):
            inspect_prefix(prefix[:100])


if __name__ == '__main__':
    unittest.main()
