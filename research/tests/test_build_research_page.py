"""dist/species-research.html is exactly what research/scripts/build_research_page.py renders from docs/species-research.md."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from research.lib.paths import ROOT


class ResearchPageTest(unittest.TestCase):
    def test_committed_page_is_the_generator_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'species-research.html'
            subprocess.run([sys.executable, str(ROOT / 'research/scripts/build_research_page.py'), str(out)], check=True)
            self.assertEqual(out.read_bytes(), (ROOT / 'dist/species-research.html').read_bytes(),
                             'regenerate with: python3 research/scripts/build_research_page.py')

    def test_page_uses_the_v2_shell(self):
        page = (ROOT / 'dist/species-research.html').read_text()
        self.assertIn('<link rel="stylesheet" href="../web/tokens.css"><link rel="stylesheet" href="coast-readable.css">', page)
        self.assertIn('<body class="coast-readable"><a class="skip-link" href="#content">', page)
        self.assertNotRegex(page, r'href="(?:tokens|styles)\.css"|class="masthead"|class="source-page"')


if __name__ == '__main__':
    unittest.main()
