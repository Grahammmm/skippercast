"""The Python package, web package and changelog must name the same release."""
import json
import re
import unittest

from skippercast import __version__
from tests._support import ROOT


class VersionAlignmentTests(unittest.TestCase):
    def test_versions_agree(self):
        web = json.loads((ROOT / "package.json").read_text())["version"]
        py = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
        latest = re.search(r"^## (?!Unreleased)(\S+)", (ROOT / "CHANGELOG.md").read_text(), re.M).group(1)
        self.assertEqual({web, py, __version__, latest}, {latest})


if __name__ == "__main__":
    unittest.main()
