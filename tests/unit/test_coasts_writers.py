"""Two writers of dist/data/coasts.json never rename each other's temporary file.

pytest-xdist ran two compile_coasts() calls at once; both used dist/data/coasts.json.tmp,
so the second rename found the file already moved (FileNotFoundError).
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.platform.coasts import compile_coasts
from skippercast.platform.contracts import REPO, atomic_json


class OverlappingWritersTests(unittest.TestCase):
    def test_a_second_compile_finishing_mid_write_leaves_both_whole(self):
        target = REPO / 'dist/data/coasts.json'
        real_replace = Path.replace
        names = []

        def replace(tmp, dest):
            # The first compile pauses before its rename while a second one of the
            # same target runs to completion.
            if Path(dest) == target:
                names.append(tmp.name)
                if len(names) == 1:
                    compile_coasts()
            return real_replace(tmp, dest)

        with patch.object(Path, 'replace', replace):
            directory = compile_coasts()
        self.assertEqual(len(names), 2)
        self.assertNotEqual(names[0], names[1])
        self.assertEqual(json.loads(target.read_text()), directory)

    def test_a_failed_unique_write_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'coasts.json'
            with patch.object(Path, 'replace', side_effect=OSError('disk')):
                with self.assertRaises(OSError):
                    atomic_json(target, {'writer': 1}, unique_tmp=True)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
