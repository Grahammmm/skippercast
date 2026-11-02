"""RF1500-8: ``fleet.ais process`` and ``backfill`` refuse an ``--mmsi`` that is not an MMSI (1..999,999,999).

Offline: ``load_region`` fails the test if it is reached for a bad value; the
good values reach a patched ``run``/``backfill`` and nothing is fetched.
"""
import argparse
import contextlib
import io
import unittest
import unittest.mock

from skippercast.fleet.ais import backfill as bf
from skippercast.fleet.ais import process
from skippercast.fleet.ais.sources.base import mmsi_arg, valid_mmsi

BAD = ["0", "-1", "1000000000", "12.5", "0x10", "true", ""]
GOOD = {"1": 1, "999999999": 999999999, "366123456": 366123456, "003669999": 3669999}
MSG = "an MMSI is a whole number from 1 to 999999999"


def _never(*args, **kwargs):
    raise AssertionError("reached the region/run for a bad --mmsi")


CLIS = {
    "process": (process, "run", ["--region", "ca"]),
    "backfill": (bf, "backfill", ["--region", "ca", "--from", "2026-05-01", "--to", "2026-05-02"]),
}


class MmsiArgTests(unittest.TestCase):
    def test_type_function(self):
        self.assertEqual(mmsi_arg("1"), 1)
        for text, value in GOOD.items():
            self.assertEqual(mmsi_arg(text), value)
        for text in BAD:
            with self.assertRaisesRegex(argparse.ArgumentTypeError, MSG):
                mmsi_arg(text)
        self.assertFalse(valid_mmsi(True))

    def _main(self, name, mmsis, *, target=_never):
        module, entry, argv = CLIS[name]
        for flag in mmsis:
            argv = argv + ["--mmsi", flag]
        err = io.StringIO()
        with unittest.mock.patch.object(module, "load_region", side_effect=target), \
                unittest.mock.patch.object(module, entry, side_effect=target), \
                unittest.mock.patch.object(module, "worker_base", return_value="https://example.invalid"), \
                unittest.mock.patch.object(process, "Worker", side_effect=lambda base: object()), \
                contextlib.redirect_stderr(err):
            try:
                code = module.main(argv)
            except SystemExit as exit_:
                code = exit_.code
        return code, err.getvalue()

    def test_bad_values_exit_2_before_region(self):
        for name in CLIS:
            for text in BAD:
                with self.subTest(cli=name, mmsi=text):
                    code, err = self._main(name, [text])
                    self.assertEqual(code, 2)
                    self.assertIn("--mmsi", err)
                    self.assertIn(MSG, err)

    def test_one_bad_among_good_runs_nothing(self):
        for name in CLIS:
            for order in (["366123456", "0"], ["1000000000", "366123456"]):
                with self.subTest(cli=name, order=order):
                    code, err = self._main(name, order)
                    self.assertEqual(code, 2)
                    self.assertIn("--mmsi", err)

    def test_good_values_reach_the_run(self):
        for name in CLIS:
            calls = []

            def record(*args, **kwargs):
                if "mmsis" in kwargs:
                    calls.append(kwargs["mmsis"])
                    return {"failed": 0} if name == "backfill" else {}
                return unittest.mock.Mock(timezone="UTC")

            with self.subTest(cli=name), contextlib.redirect_stdout(io.StringIO()):
                code, err = self._main(name, list(GOOD) + ["1"], target=record)
                self.assertEqual(code, 0, err)
                self.assertEqual(calls, [list(GOOD.values()) + [1]])


if __name__ == "__main__":
    unittest.main()
