"""The Python package, web package, changelog and README must name the same release; the health endpoint reads package.json."""
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

    def test_readme_status_names_the_same_release(self):
        # The README says "version 0.8" (major.minor, as its prose always has), the package says "0.8.0".
        # Compare the README's figure to the same-length leading part of package.json's version, so the
        # prose keeps its style, a patch release needs no README edit, and "0.3", "0.7" or "0.8.1" all fail.
        web = json.loads((ROOT / "package.json").read_text())["version"]
        said = re.search(r"^A working mobile web app, version (\d+\.\d+(?:\.\d+)?)(?!\d|\.\d)", (ROOT / "README.md").read_text(), re.M)
        self.assertIsNotNone(said, "README.md Status line must still say 'A working mobile web app, version X.Y'")
        stated = said.group(1)
        self.assertEqual(stated, ".".join(web.split(".")[: stated.count(".") + 1]), f"README says version {stated} but package.json is {web}")

    def test_health_endpoint_reads_package_json(self):
        # tests/test_worker_routes.mjs checks the served value; this keeps a second literal from coming back.
        public = (ROOT / "server/routes/public.ts").read_text()
        self.assertIn("from '../../package.json' with {type: 'json'}", public)
        self.assertIn("version: pkg.version", public)


if __name__ == "__main__":
    unittest.main()
