import unittest
from datetime import datetime, timezone
from unittest import mock

from skippercast.coastal.coordinator import packet_release as pr

BIG = 10 ** 400


class HorizonClockTests(unittest.TestCase):
    def test_oversized_clocks_refuse_as_valueerror(self):
        for sign in (1, -1):
            for args in ((sign * BIG, 1000), (100, sign * BIG)):
                with self.assertRaises(ValueError):
                    pr._horizon(*args)

    def test_public_refusal_precedes_metadata_and_writes(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(pr, 'metadata_document') as md, \
                mock.patch.object(pr, 'implementation_hashes') as ih, \
                mock.patch.object(pr, 'write') as wr:
            for sign in (1, -1):
                for kw in (dict(now=sign * BIG, horizon=1000), dict(now=100, horizon=sign * BIG)):
                    with self.assertRaises(ValueError):
                        pr.validate_acquisition_package(d, 'g', [], **kw)
                    with self.assertRaises(ValueError):
                        pr.build_acquisition_package(d, 'g', [], rights={}, trial={}, segment={}, **kw)
            self.assertEqual(os.listdir(d), [])
            md.assert_not_called(); ih.assert_not_called(); wr.assert_not_called()

    def test_accepted_representations_unchanged(self):
        self.assertEqual(pr._horizon(100, 3700), (100.0, 3700.0))
        self.assertEqual(pr._horizon(100.5, 200.25), (100.5, 200.25))
        a = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t = a.timestamp()
        self.assertEqual(pr._horizon(a, t + 3600), (t, t + 3600))
        for bad in ((100, 3701), (100, 100), (200, 100)):
            with self.assertRaises(ValueError):
                pr._horizon(*bad)

    def test_boolean_and_nonfinite_still_refused(self):
        for args in ((True, 5), (1, False), (float('nan'), 5), (1, float('inf'))):
            with self.assertRaises(ValueError):
                pr._horizon(*args)


if __name__ == '__main__':
    unittest.main()
