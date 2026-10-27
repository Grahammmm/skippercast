"""Declared root aliases must work without normalizing away artifact traversal."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.coastal.handoff import common


class ReferencePathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name).resolve()
        self.root = self.parent / 'root'
        self.root.mkdir()
        self.alias = self.parent / 'declared-root-alias'
        self.alias.symlink_to(self.root, target_is_directory=True)
        self.payload = b'retained-fixture'
        self.artifact = self.root / 'artifact.bin'
        self.artifact.write_bytes(self.payload)

    def test_declared_root_alias_accepts_absolute_child(self):
        reference = common.ref(self.alias, self.alias / 'artifact.bin', 'synthetic')
        self.assertEqual(reference, dict(path='artifact.bin', bytes=len(self.payload),
                         sha256=hashlib.sha256(self.payload).hexdigest(), contract='synthetic'))
        self.assertEqual(common.resolve(self.alias, reference), self.artifact)

    def test_declared_root_alias_accepts_canonical_absolute_child(self):
        self.assertEqual(common.ref(self.alias, self.artifact, 'synthetic'),
                         common.ref(self.root, 'artifact.bin', 'synthetic'))

    def test_canonical_root_absolute_and_relative_references_agree(self):
        self.assertEqual(common.ref(self.root, self.artifact, 'synthetic'),
                         common.ref(self.root, 'artifact.bin', 'synthetic'))

    def test_store_constructor_canonicalizes_declared_root(self):
        from skippercast.coastal.coordinator.store import Store
        store = Store(':memory:', root=self.alias)
        try:
            self.assertEqual(store.root, self.root)
        finally:
            store.close()

    def test_absolute_and_relative_traversal_are_refused_before_hashing(self):
        (self.root / 'nested').mkdir()
        for path in (Path('nested/../artifact.bin'), self.root / 'nested/../artifact.bin',
                     self.alias / 'nested/../artifact.bin'):
            with self.subTest(path=path), patch.object(common, 'sha', side_effect=AssertionError('hash called')):
                with self.assertRaises(ValueError):
                    common.ref(self.alias, path, 'synthetic')

    def test_artifact_symlinks_are_refused_before_hashing(self):
        (self.root / 'linked-file').symlink_to(self.artifact)
        (self.root / 'linked-inside-dir').symlink_to(self.root, target_is_directory=True)
        outside = self.parent / 'outside'
        outside.mkdir()
        (outside / 'artifact.bin').write_bytes(b'outside')
        (self.root / 'linked-outside-dir').symlink_to(outside, target_is_directory=True)
        (self.root / 'broken-link').symlink_to(self.root / 'absent')
        for name in ('linked-file', 'linked-inside-dir/artifact.bin',
                     'linked-outside-dir/artifact.bin', 'broken-link'):
            for path in (name, self.root / name, self.alias / name):
                with self.subTest(path=path), patch.object(common, 'sha', side_effect=AssertionError('hash called')):
                    with self.assertRaises(ValueError):
                        common.ref(self.alias, path, 'synthetic')

    def test_outside_and_undeclared_absolute_aliases_are_refused(self):
        sibling = self.parent / 'root-sibling'
        sibling.mkdir()
        outside = sibling / 'artifact.bin'
        outside.write_bytes(b'outside')
        for path in (outside, self.alias / 'artifact.bin'):
            with self.subTest(path=path), patch.object(common, 'sha', side_effect=AssertionError('hash called')):
                with self.assertRaises(ValueError):
                    common.ref(self.root, path, 'synthetic')

    def test_missing_artifact_is_refused(self):
        with self.assertRaises(ValueError):
            common.ref(self.alias, self.alias / 'absent', 'synthetic')

    def test_alias_reference_keeps_byte_caps_and_hash_verification(self):
        with self.assertRaises(ValueError):
            common.ref(self.alias, self.alias / 'artifact.bin', 'synthetic', cap=1)
        reference = common.ref(self.alias, self.alias / 'artifact.bin', 'synthetic')
        self.artifact.write_bytes(b'x' * len(self.payload))
        with self.assertRaises(ValueError):
            common.resolve(self.alias, reference)


if __name__ == '__main__':
    unittest.main()
