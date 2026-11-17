"""RF1951-4: explicit CDIP DAP array chunk offsets must be contiguous from zero or the array refuses."""

from unittest import TestCase

from skippercast.pipeline import cdip_nearshore as cdip


def body(*lines, size=4):
    return f"Dataset {{\n}} d;\n-----------------\n\nwaveHs[{size}]\n" + "\n".join(lines) + "\n"


class ChunkOffsetTests(TestCase):
    def test_duplicate_or_backward_chunk_offset_is_refused(self):
        for label, lines in (("duplicate", ("[0], 1, 2,", "[0], 9, 8")),
                             ("backward", ("[2], 3, 4,", "[0], 1, 2"))):
            with self.subTest(label), self.assertRaises(ValueError):
                cdip.parse_dap_ascii(body(*lines))

    def test_gapped_or_out_of_range_chunk_offset_is_refused(self):
        for label, lines in (("gap", ("[0], 1, 2,", "[3], 9, 8")),
                             ("first nonzero", ("[1], 1, 2,", "[3], 3, 4")),
                             ("beyond end", ("[0], 1, 2, 3, 4,", "[4], 5")),
                             ("multidimensional", ("[0][0], 1, 2,", "[2][0], 3, 4"))):
            with self.subTest(label), self.assertRaises(ValueError):
                cdip.parse_dap_ascii(body(*lines))

    def test_empty_indexed_chunks_are_refused(self):
        for label, lines, size in (
            ("duplicate start", ("[0],", "[0], 1, 2, 3, 4"), 4),
            ("past end", ("[0], 1, 2, 3, 4,", "[4],"), 4),
            ("empty middle", ("[0], 1, 2,", "[2],", "[2], 3, 4"), 4),
            ("zero length", ("[0],",), 0),
        ):
            with self.subTest(label), self.assertRaises(ValueError):
                cdip.parse_dap_ascii(body(*lines, size=size))

    def test_contiguous_indexed_chunks_preserve_values(self):
        for label, lines in (("two chunks", ("[0], 1, 2,", "[2], 3, 4")),
                             ("one-value chunks", ("[0], 1,", "[1], 2,", "[2], 3,", "[3], 4")),
                             ("no comma", ("[0] 1, 2,", "[2] 3, 4"))):
            with self.subTest(label):
                self.assertEqual(cdip.parse_dap_ascii(body(*lines)), {"waveHs": [1.0, 2.0, 3.0, 4.0]})

    def test_unindexed_arrays_and_scalar_controls_are_unchanged(self):
        self.assertEqual(cdip.parse_dap_ascii(body("1, 2, 3, 4")), {"waveHs": [1.0, 2.0, 3.0, 4.0]})
        self.assertEqual(cdip.parse_dap_ascii(body(size=0)), {"waveHs": []})
        text = 'Dataset {\n} d;\n-----------------\n\nmetaSiteLabel, "SL1"\n'
        self.assertEqual(cdip.parse_dap_ascii(text), {"metaSiteLabel": ["SL1"]})
