"""Files whose bytes are part of the seafloor pipeline's cache keys.

seafloor/ingest.py keys each normalized survey grid (COG) on the SHA-256 of
these source files, and legacy sources require the reviewed
``adapter_review.cog_sha256`` in catalog/surveys.json. Sources with a reviewed
raster content identity also accept a different lossless file encoding, only
when every scientific pixel, mask and grid field matches. Any byte change here,
even a refactor or a new import, turns every cached grid into a cache miss.
Normalizing again on a different machine does not reproduce the reviewed
bytes, so the scheduled "Screen and publish seafloor" job fails with
"Normalized source differs from reviewed manifest" and the public layer stays
unavailable.

That happened on 2026-09-29, when a shared-helper refactor edited
platform/bottom_targets.py. To change one of these files, do it in a seafloor
PR that re-runs ingestion, re-reviews the COG hashes and updates this list in
the same change.
"""
import hashlib
import unittest
from tests._support import ROOT


PINNED = {
    # seafloor/ingest.py: metadata_parser and implementation
    'src/skippercast/platform/bottom_targets.py': 'feece80a42529aeab5850bc4b775835ffdcafdbb779ac38d6e3cc7c33c7d192f',
    'src/skippercast/seafloor/ingest.py': 'b3427fc82f962a41d0e36a9962eee13354c06f40e0aac21255f6eb7738aec358',
    'src/skippercast/seafloor/raster.py': 'efa6606e5205670186ec16f0625bd2077bc7b0ff574266f07d6f01ec91902da8',
    'src/skippercast/seafloor/adapters/arcgrid.py': 'a850c5f405a55abe348cce9911dc6df72d2126a2ade1f4a2475e3f6bd29b2bc2',
    'src/skippercast/seafloor/adapters/bag.py': 'f89211791ecc448f3d8d4b32589ee4c7cc016604e7788db46b17405c9858853c',
    'src/skippercast/seafloor/adapters/usgs_geotiff.py': '51dee0633a7733c9937856b3c09704b8f5197bf9c96e3dc5f3d2aa8b65f4a24a',
}


class SeafloorKeyFileTests(unittest.TestCase):
    def test_key_files_keep_their_reviewed_bytes(self):
        for name, expected in PINNED.items():
            with self.subTest(name):
                actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                self.assertEqual(actual, expected, f'{name} is part of a seafloor cache key; see this module docstring')

    def test_pinned_list_covers_every_file_the_keys_hash(self):
        ingest = (ROOT / 'src/skippercast/seafloor/ingest.py').read_text()
        for name in ('ingest.py', 'raster.py', 'adapters/bag.py', 'adapters/usgs_geotiff.py', 'adapters/arcgrid.py'):
            self.assertIn(f"'{name}'", ingest)
            self.assertIn(f'src/skippercast/seafloor/{name}', PINNED)
        self.assertIn("'platform/bottom_targets.py'", ingest)


    def test_changing_a_key_file_triggers_the_seafloor_workflow(self):
        # A key-file change must re-run ingestion on main, so the workflow's
        # push filter has to cover every pinned file.
        from fnmatch import fnmatch
        workflow = (ROOT / '.github/workflows/seafloor.yml').read_text()
        push = workflow.split('push:', 1)[1].split('paths:', 1)[1]
        patterns = []
        for line in push.splitlines()[1:]:
            stripped = line.strip()
            if not stripped.startswith('- '):
                break
            patterns.append(stripped[2:].strip().strip("'\""))
        for name in PINNED:
            with self.subTest(name):
                self.assertTrue(any(fnmatch(name, p.replace('**', '*')) for p in patterns), f'{name} is not in seafloor.yml push paths')


if __name__ == '__main__':
    unittest.main()
