"""Research tooling stays out of the product path (engineering audit P1-02).

research/ holds dated audit, screening and discovery scripts. Product code must
never import or run it, and new research scripts must not land in scripts/.
"""
import ast
import json
from pathlib import Path
import py_compile
import re
import tempfile
import unittest
from tests._support import ROOT

# Research prefixes; a product tool that happens to share one is listed explicitly.
RESEARCH_PREFIXES = ('audit_', 'screen_', 'triage_', 'review_', 'discover_', 'inspect_', 'summarize_',
                     'queue_', 'compile_', 'reconcile_', 'measure_', 'qualify_', 'merge_', 'split_',
                     'assess_', 'fetch_', 'import_', 'inventory_')
# Run by daily-data.yml; their outputs (survey-discovery.json, survey-products.json) are loaded by the app.
# measure_startup.mjs measures the app itself; the startup budget browser test (e2e/startup.spec.ts) runs it.
PRODUCT_EXCEPTIONS = {'audit_noaa_survey_products.py', 'discover_noaa_surveys.py', 'measure_startup.mjs'}
JS_RESEARCH_IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*)['"][^'"]*\bresearch/""")


def python_imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'), str(path))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module


class ResearchBoundaryTest(unittest.TestCase):
    def test_product_python_never_imports_research(self):
        paths = [*sorted((ROOT / 'src').rglob('*.py')), *sorted((ROOT / 'scripts').glob('*.py'))]
        offenders = [f'{p.relative_to(ROOT)}: {m}' for p in paths for m in python_imports(p)
                     if m.split('.')[0] == 'research']
        self.assertEqual(offenders, [])

    def test_product_scripts_never_run_research(self):
        offenders = [p.name for p in sorted((ROOT / 'scripts').iterdir())
                     if p.suffix in {'.py', '.sh', '.mjs'} and 'research/' in p.read_text(encoding='utf-8')]
        self.assertEqual(offenders, [])

    def test_web_and_worker_never_import_research(self):
        paths = [*sorted((ROOT / 'dist').glob('*.js')), *sorted((ROOT / 'dist').glob('*.html')),
                 *sorted((ROOT / 'server').rglob('*.[jt]s'))]
        offenders = [p.relative_to(ROOT).as_posix() for p in paths
                     if JS_RESEARCH_IMPORT.search(p.read_text(encoding='utf-8'))]
        self.assertEqual(offenders, [])

    def test_app_and_worker_do_not_load_receipts(self):
        # Receipts left dist/data/ (P1-02b); the published client must not depend on them.
        manifest = json.loads((ROOT / 'research/receipts/manifest.json').read_text())['files']
        shipped = [*sorted((ROOT / 'dist').glob('*.js')), *sorted((ROOT / 'dist').glob('*.html')),
                   *sorted((ROOT / 'server').rglob('*.[jt]s'))]
        text = {p.relative_to(ROOT).as_posix(): p.read_text(encoding='utf-8') for p in shipped}
        loaded = sorted(f'{path}: {name}' for name in manifest for path, body in text.items()
                        if re.search(r'(?<![\w.-])' + re.escape(name) + r'(?![\w-])', body))
        self.assertEqual(loaded, [])
        self.assertEqual(sorted(set(manifest) & {p.name for p in (ROOT / 'dist/data').iterdir()}), [],
                         'a receipt is back in dist/data/; research receipts belong in research/receipts/')

    def test_product_workflows_run_no_research(self):
        # P1-02c: research runs only in research-*.yml, so it can never gate a product feed.
        offenders = [p.name for p in sorted((ROOT / '.github/workflows').glob('*.yml'))
                     if not p.name.startswith('research-') and 'research/' in p.read_text()]
        self.assertEqual(offenders, [])

    def test_research_workflows_publish_nothing(self):
        # Artifacts only: read-only token, and feed publishers may only be used to --load.
        publisher = re.compile(r'(publish_branch_snapshot\.sh(?! --load)|publish_branch_r2\.sh|publish_r2\.py|'
                               r'publish_forecasts\.sh|contents:\s*write|git push)')
        workflows = sorted((ROOT / '.github/workflows').glob('research-*.yml'))
        self.assertGreaterEqual(len(workflows), 3)
        for path in workflows:
            with self.subTest(path.name):
                text = path.read_text()
                self.assertRegex(text, r'(?m)^permissions:\n  contents: read$')
                self.assertIsNone(publisher.search(text))

    def test_new_research_scripts_do_not_land_in_scripts(self):
        misplaced = [p.name for p in sorted((ROOT / 'scripts').iterdir())
                     if p.name.startswith(RESEARCH_PREFIXES) and p.name not in PRODUCT_EXCEPTIONS]
        self.assertEqual(misplaced, [], 'put dated audit/research tooling in research/scripts/')

    def test_research_scripts_compile(self):
        # Import needs the GIS packages; syntax is checked everywhere so a moved
        # script cannot silently rot in the core job.
        with tempfile.TemporaryDirectory() as tmp:
            for path in sorted((ROOT / 'research').rglob('*.py')):
                py_compile.compile(str(path), cfile=str(Path(tmp) / 'x.pyc'), doraise=True)


if __name__ == '__main__':
    unittest.main()
