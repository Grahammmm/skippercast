"""Terrain-support bindings may not select the depth product by path alias."""
from copy import deepcopy
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skippercast.seafloor import terrain_support as support
from skippercast.seafloor.adapters import arcgrid

DEPTH = 'native/depth'
SAME = 'Terrain support must select a separate categorical product'


def make_row(member='native/classes', depth=DEPTH):
    return {
        'id': 'src', 'kind': 'bathymetry', 'format': 'arcgrid', 'sha256': 'a' * 64,
        'archive_member': depth, 'evidence': ['e1'], 'resolution_m': 2,
        'adapter_review': {'cog_sha256': 'b' * 64},
        'terrain_support': {
            'profile': 'csumb-native-rough-v1', 'rough_codes': list(support.ROUGH_CODES),
            'smooth_codes': list(support.SMOOTH_CODES), 'reviewed_on': '2020-01-01',
            'evidence': ['e1'], 'depth_source_id': 'src', 'source_sha256': 'a' * 64,
            'depth_archive_member': depth, 'depth_cog_sha256': 'b' * 64,
            'archive_member': member, 'metadata_sha256': 'c' * 64},
    }


class MemberIdentityTests(unittest.TestCase):
    def test_canonical_same_member_refused(self):
        for member in (DEPTH, DEPTH + '/', DEPTH + '//'):
            with self.subTest(member=member), self.assertRaisesRegex(ValueError, SAME):
                support.validate_binding(make_row(member))

    def test_dot_and_repeated_separator_aliases_refused(self):
        aliases = ('native/./depth', 'native//depth', './native/depth', './native//./depth/')
        for alias in aliases:
            with self.subTest(binding=alias), self.assertRaisesRegex(ValueError, SAME):
                support.validate_binding(make_row(alias))
            with self.subTest(row=alias), self.assertRaisesRegex(ValueError, SAME):
                support.validate_binding(make_row(DEPTH, depth=alias))

    def test_nested_zip_alias_is_same_product(self):
        base = 'outer/data.zip/grid'
        for alias in ('outer//data.zip/grid', 'outer/./data.zip/grid', 'outer/data.zip/./grid',
                      'outer/data.zip//grid/'):
            with self.subTest(alias=alias), self.assertRaisesRegex(ValueError, SAME):
                support.validate_binding(make_row(alias, depth=base))
        support.validate_binding(make_row('outer/Data.zip/grid', depth=base))

    def test_distinct_product_preserves_original_binding(self):
        for member in ('native/classes', 'native/./classes', 'native//classes/'):
            row = make_row(member)
            before = deepcopy(row)
            digest = support.binding_digest(row)
            support.validate_binding(row)
            self.assertEqual(row, before)
            self.assertEqual(support.binding_digest(row), digest)
            self.assertEqual(support.feature_evidence(row)['archive_member'], member)

    def test_unsafe_paths_still_refused_first(self):
        for member in ('/native/depth', 'native/../depth', 'native\\depth', 'c:depth'):
            with self.subTest(member=member), self.assertRaisesRegex(ValueError, 'Unsafe'):
                support.validate_binding(make_row(member))

    def test_synthetic_extraction_identity_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp)/'source.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                for name, data in (('native/depth/hdr.adf', b'h'), ('native/depth/prj.adf', b'p')):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            dirs = set()
            for alias in (DEPTH, 'native/./depth', 'native//depth', './native/depth'):
                dirs.add(arcgrid.source_path(archive, {'archive_member': alias}))
                with self.assertRaisesRegex(ValueError, SAME):
                    support.validate_binding(make_row(alias))
            self.assertEqual(len(dirs), 1)

    def test_native_reader_refuses_before_fetch(self):
        row = make_row('native//depth')
        with patch('skippercast.seafloor.fetch.fetch_source') as fetch, \
                patch('skippercast.seafloor.io.sha256') as digest:
            with self.assertRaisesRegex(ValueError, SAME):
                with support.native_reader({'row': row, 'path': 'x'}, root='.'):
                    pass
        fetch.assert_not_called()
        digest.assert_not_called()


if __name__ == '__main__':
    unittest.main()
