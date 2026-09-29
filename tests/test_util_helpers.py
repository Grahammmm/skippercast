"""Shared helpers reproduce each replaced call site's output exactly (P2-07)."""
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from skippercast.forecast import build as forecast_build
from skippercast.pipeline import collect
from skippercast.platform import bottom_targets, contracts
from skippercast.seafloor import io as seafloor_io
from skippercast.util.hashing import sha256_file
from skippercast.util.time import stamp


# The implementations these helpers replaced, verbatim, as the reference.
def contracts_and_collect_stamp(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def forecast_stamp(moment=None):
    moment = moment or datetime.now(timezone.utc)
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def seafloor_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def bottom_targets_sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


MOMENTS = [
    datetime(2026, 9, 28, 12, 7, 40, tzinfo=timezone.utc),
    datetime(2026, 9, 28, 12, 7, 40, 999999, tzinfo=timezone.utc),
    datetime(2026, 9, 28, 5, 7, 40, tzinfo=timezone(timedelta(hours=-7))),
    datetime(2026, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
    datetime(2026, 9, 28, 12, 7, 40),  # naive
]


class StampTests(unittest.TestCase):
    def test_default_matches_contracts_and_collect(self):
        for moment in MOMENTS:
            self.assertEqual(stamp(moment), contracts_and_collect_stamp(moment), moment)
        self.assertRegex(stamp(), r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')

    def test_forecast_format_is_preserved(self):
        for moment in MOMENTS:
            self.assertEqual(stamp(moment, to_utc=False), forecast_stamp(moment), moment)
            self.assertEqual(forecast_build.stamp(moment), forecast_stamp(moment), moment)
        # The two formats agree for the UTC times the pipeline actually passes.
        self.assertEqual(stamp(MOMENTS[0], to_utc=False), stamp(MOMENTS[0]))

    def test_call_sites_use_the_shared_helper(self):
        self.assertIs(contracts.stamp, stamp)
        self.assertIs(collect.stamp, stamp)


class HashTests(unittest.TestCase):
    def test_matches_both_replaced_implementations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for size in (0, 1, 1024 * 1024 - 1, 1024 * 1024, 3 * 1024 * 1024 + 7):
                path = root / f'{size}.bin'
                path.write_bytes(bytes(i % 251 for i in range(size)))
                expected = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(sha256_file(path), expected)
                self.assertEqual(seafloor_sha256(path), expected)
                self.assertEqual(bottom_targets_sha256(path), expected)
                self.assertEqual(sha256_file(str(path)), expected)

    def test_seafloor_key_files_keep_their_own_equivalent_copies(self):
        # platform/bottom_targets.py is hashed into the seafloor ingestion
        # cache key, so it keeps its reviewed bytes and its own sha256
        # (tests/test_seafloor_key_files.py). It must still agree with the
        # shared helper; seafloor/io.py re-exports the shared helper.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.bin'
            path.write_bytes(bytes(range(256)) * 5000)
            self.assertEqual(bottom_targets.sha256(path), sha256_file(path))
        self.assertIs(seafloor_io.sha256, sha256_file)


class LintConfigTests(unittest.TestCase):
    def test_ci_and_dev_extra_pin_the_same_ruff(self):
        import re
        import tomllib
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / 'pyproject.toml').read_text())
        dev = [pin for pin in project['project']['optional-dependencies']['dev'] if pin.startswith('ruff==')]
        ci = re.findall(r'ruff==[0-9.]+', (root / '.github/workflows/ci.yml').read_text())
        self.assertEqual(len(dev), 1)
        self.assertEqual(set(ci), set(dev))
        self.assertEqual(project['tool']['ruff']['lint']['select'], ['E9', 'F63', 'F7', 'F82'])


if __name__ == '__main__':
    unittest.main()
