"""Cardinality boundary through the real mosaic API, using generated NPZ samples."""
import copy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from skippercast.seafloor import grid
from tests.fixtures.sc62.factory import make_case


class SinglePass:
    def __init__(self, values):
        self.values = values
        self.calls = 0

    def __iter__(self):
        self.calls += 1
        if self.calls != 1:
            raise AssertionError('input iterated more than once')
        return iter(self.values)


class ReferencePairingTests(unittest.TestCase):
    def setUp(self):
        # Under the runner, retain every input under its unique run root. Normal
        # repository discovery uses its own normal temporary lifetime instead.
        self.temporary = None
        if os.environ.get('SC62_DATA_ROOT'):
            base = Path(tempfile.mkdtemp(dir=os.environ['SC62_DATA_ROOT']))
        else:
            self.temporary = tempfile.TemporaryDirectory()
            base = Path(self.temporary.name)
            self.addCleanup(self.temporary.cleanup)
        self.config, self.tiles, self.samples, self.expected, self.affine = make_case(base / 'samples')
        self.before = self.snapshot()
        self.rows = copy.deepcopy(self.tiles)
        self.receipts = copy.deepcopy([r for _, r in self.samples])

    def snapshot(self):
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p, _ in self.samples}

    def tearDown(self):
        self.assertEqual(self.before, self.snapshot())
        self.assertEqual(self.rows, self.tiles)
        self.assertEqual(self.receipts, [r for _, r in self.samples])

    def test_complete_two_pair_mosaic(self):
        actual, affine = grid.mosaic_reference(self.config, self.tiles, self.samples)
        np.testing.assert_array_equal(actual, self.expected)
        self.assertEqual(affine, self.affine)
        self.assertEqual(actual.dtype, np.dtype('uint8'))

    def test_iterable_forms_materialized_once(self):
        for form in (list, tuple, lambda x: (v for v in x), SinglePass):
            with self.subTest(form=form):
                tiles, samples = form(self.tiles), form(self.samples)
                actual, affine = grid.mosaic_reference(self.config, tiles, samples)
                np.testing.assert_array_equal(actual, self.expected)
                self.assertEqual(affine, self.affine)
                if isinstance(tiles, SinglePass):
                    self.assertEqual((tiles.calls, samples.calls), (1, 1))

    def test_both_empty_preserves_grid(self):
        for tiles, samples in (([], []), ((), ()), ((v for v in []), (v for v in []))):
            actual, affine = grid.mosaic_reference(self.config, tiles, samples)
            np.testing.assert_array_equal(actual, np.zeros((10, 10), dtype='uint8'))
            self.assertEqual(affine, self.affine)

    def mismatch(self, tiles, samples):
        # Earlier successful output must not be mutated by any refused request.
        prior, affine = grid.mosaic_reference(self.config, self.tiles, self.samples)
        before = prior.copy()
        with patch.object(grid, 'transform_bounds', wraps=grid.transform_bounds) as project, \
                patch.object(grid.np, 'zeros', wraps=grid.np.zeros) as allocate, \
                patch.object(grid.np, 'load', wraps=grid.np.load) as load:
            with self.assertRaisesRegex(ValueError, 'reference_tile_sample_count_mismatch'):
                grid.mosaic_reference(self.config, tiles, samples)
            project.assert_not_called()
            allocate.assert_not_called()
            load.assert_not_called()
        np.testing.assert_array_equal(prior, before)
        self.assertEqual(affine, self.affine)

    def test_fewer_samples_rejected_before_work(self):
        self.mismatch(self.tiles, self.samples[:1])

    def test_extra_samples_rejected_before_work(self):
        self.mismatch(self.tiles, self.samples + self.samples[:1])

    def test_empty_samples_rejected_before_work(self):
        self.mismatch(self.tiles, [])

    def test_empty_tiles_rejected_before_work(self):
        self.mismatch([], self.samples)

    def test_mismatched_single_pass_inputs(self):
        tiles, samples = SinglePass(self.tiles), SinglePass(self.samples[:1])
        self.mismatch(tiles, samples)
        self.assertEqual((tiles.calls, samples.calls), (1, 1))

    def test_same_length_reordered_pairs_not_rematched(self):
        actual, affine = grid.mosaic_reference(self.config, self.tiles, self.samples[::-1])
        # Positional association is preserved: the coarse sample is now attached
        # to the fine tile and overwrites fine land with its valid water.
        expected = self.expected.copy()
        expected[2:8, 2:8] = 2
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(affine, self.affine)
        # Reordering complete pairs, in contrast, cannot change precedence.
        actual, _ = grid.mosaic_reference(self.config, self.tiles[::-1], self.samples[::-1])
        np.testing.assert_array_equal(actual, self.expected)

    def test_resolution_date_id_precedence(self):
        variants = [
            ({'native_resolution_m': 50, 'delivered_date': '2026-12-01', 'id': 'z'},
             {'native_resolution_m': 25, 'delivered_date': '2026-01-01', 'id': 'a'}),
            ({'native_resolution_m': 25, 'delivered_date': '2026-01-01', 'id': 'z'},
             {'native_resolution_m': 25, 'delivered_date': '2026-02-01', 'id': 'a'}),
            ({'native_resolution_m': 25, 'delivered_date': '2026-01-01', 'id': 'a'},
             {'native_resolution_m': 25, 'delivered_date': '2026-01-01', 'id': 'z'}),
        ]
        for tiles in variants:
            for reverse in (False, True):
                with self.subTest(tiles=tiles, reverse=reverse):
                    actual, affine = grid.mosaic_reference(
                        self.config, tiles[::-1] if reverse else tiles,
                        self.samples[::-1] if reverse else self.samples)
                    np.testing.assert_array_equal(actual, self.expected)
                    self.assertEqual(affine, self.affine)
