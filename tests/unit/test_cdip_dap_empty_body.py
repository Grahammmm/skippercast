"""SCA1123-2323-11: a CDIP DAP2 response with an empty data body refuses by name, not IndexError."""

from unittest import TestCase

from skippercast.pipeline import cdip_nearshore as cdip

HEADER = "Dataset {\n    Float32 metaLatitude;\n} cdip;\n"
RULE = "---------------------------------------------\n"
NAMED = "Invalid DAP ASCII response"


class EmptyDataBodyTests(TestCase):
    # Contract: a response with a separator but no data is a refused read (ValueError), which
    # callers handle; a bare IndexError from lines[0] would crash the nearshore model stage.
    def test_separator_with_nothing_after_it_refuses_by_name(self):
        with self.assertRaisesRegex(ValueError, NAMED):
            cdip.parse_dap_ascii(HEADER + RULE)

    def test_separator_followed_by_blank_lines_refuses_by_name(self):
        with self.assertRaisesRegex(ValueError, NAMED):
            cdip.parse_dap_ascii(HEADER + RULE + "\n\n\n")

    def test_separator_followed_by_whitespace_only_lines_refuses_by_name(self):
        # A trailing-space or tab-only line must not slip past a naive `== ""` check.
        with self.assertRaisesRegex(ValueError, NAMED):
            cdip.parse_dap_ascii(HEADER + RULE + "  \n\t\n  \n")

    # Unaffected controls: the check must not touch groups that do have data.
    def test_healthy_scalar_still_parses(self):
        self.assertEqual(cdip.parse_dap_ascii(HEADER + RULE + "metaLatitude, 35.2\n"),
                         {"metaLatitude": [35.2]})

    def test_healthy_array_still_parses(self):
        self.assertEqual(cdip.parse_dap_ascii(HEADER + RULE + "waveHs[2]\n[0], 1.5, 1.7\n"),
                         {"waveHs": [1.5, 1.7]})

    def test_body_without_separator_still_refuses_by_name(self):
        with self.assertRaisesRegex(ValueError, NAMED):
            cdip.parse_dap_ascii(HEADER)
