"""atomic_json: two writers of one target never rename each other's temporary file.

pytest-xdist ran two compile_coasts() calls at once; both used dist/data/coasts.json.tmp,
so the second rename found the file already moved (FileNotFoundError).
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.platform.contracts import atomic_json


class OverlappingWritersTests(unittest.TestCase):
    def test_a_second_writer_finishing_mid_write_leaves_both_writes_whole(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'coasts.json'
            real_replace = Path.replace
            calls = []

            def replace(tmp, dest):
                # The first writer pauses before its rename while a second writer
                # of the same target runs to completion.
                calls.append(tmp.name)
                if len(calls) == 1:
                    atomic_json(target, {'writer': 2})
                return real_replace(tmp, dest)

            with patch.object(Path, 'replace', replace):
                atomic_json(target, {'writer': 1})
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(calls[0], calls[1])
            self.assertEqual(json.loads(target.read_text()), {'writer': 1})
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['coasts.json'])

    def test_a_failed_write_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'coasts.json'
            with patch.object(Path, 'replace', side_effect=OSError('disk')):
                with self.assertRaises(OSError):
                    atomic_json(target, {'writer': 1})
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
