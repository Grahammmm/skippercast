"""Offline N3 coverage contract; fixtures are allocated outside committed inputs."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.coast_diagnostics import rights_coverage as coverage
from tests._support import ROOT


class RightsCoverageTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get('N3_FIXTURE_ROOT')
        self.root = Path(tempfile.mkdtemp(prefix='n3-fixture-', dir=parent))
        (self.root / 'catalog/candidates').mkdir(parents=True)
        template = ROOT / 'tests/fixtures/n3_rights_coverage/federal.json'
        self.row = json.loads(template.read_text())
        self.recipe = self.root / 'recipe.json'
        self.write_sources([self.row])
        self.write_recipe(['federal'])

    def write_sources(self, rows):
        (self.root / 'catalog/sources.json').write_text(json.dumps({'sources': rows}))

    def write_recipe(self, slugs):
        self.recipe.write_text(json.dumps({'sources': slugs}))

    def report(self):
        return coverage.check_coverage(self.root, self.recipe)

    def test_all_resolve_complete(self):
        report = self.report()
        self.assertEqual(report['verdict'], 'COMPLETE')
        self.assertEqual(report['lacking_rights'], [])
        self.assertEqual(report['sources'][0]['rights']['license'], 'public-domain-us-gov')
        self.assertTrue(report['sources'][0]['attribution_present'])

    def test_missing_catalog_incomplete(self):
        self.write_recipe(['federal', 'missing'])
        report = self.report()
        self.assertEqual(report['verdict'], 'INCOMPLETE', 'missing catalog slug must prevent COMPLETE')
        self.assertEqual(report['lacking_rights'], ['missing'])
        self.assertEqual(report['sources'][1]['error']['type'], 'CatalogEntryMissing')
        self.assertFalse(report['sources'][1]['catalog_found'])

    def test_existing_value_error_recorded(self):
        self.row['license'] = 'unqualified'
        self.write_sources([self.row])
        report = self.report()
        self.assertEqual(report['verdict'], 'INCOMPLETE')
        self.assertEqual(report['sources'][0]['error']['type'], 'ValueError')
        self.assertIn('unqualified', report['sources'][0]['error']['message'])

    def test_blank_attribution_incomplete(self):
        self.row['publisher'] = '  '
        self.write_sources([self.row])
        report = self.report()
        self.assertEqual(report['verdict'], 'INCOMPLETE')
        self.assertFalse(report['sources'][0]['attribution_present'])
        self.assertEqual(report['lacking_rights'], ['federal'])

    def test_candidate_entry_resolves(self):
        self.write_sources([])
        (self.root / 'catalog/candidates/federal.json').write_text(json.dumps(self.row))
        report = self.report()
        self.assertEqual(report['verdict'], 'COMPLETE')
        self.assertEqual(report['sources'][0]['catalog_locators'], ['catalog/candidates/federal.json'])

    def test_duplicate_catalog_id_is_ambiguous(self):
        (self.root / 'catalog/candidates/other.json').write_text(json.dumps(self.row))
        report = self.report()
        self.assertEqual(report['verdict'], 'INCOMPLETE')
        self.assertEqual(report['sources'][0]['error']['type'], 'CatalogEntryAmbiguous')

    def test_no_url_paths_credentials_or_queries_in_output(self):
        self.row['publisher'] = 'Credit https://user:password@example.test/private?q=secret#frag'
        self.write_sources([self.row])
        report = self.report()
        text = json.dumps(report) + coverage.render_table(report)
        for forbidden in ('https:', '/private', 'password', 'q=secret', '#frag', '/data/file'):
            self.assertNotIn(forbidden, text)
        self.assertIn('example.test', text)
        self.assertIn('records.example.test', text)

    def test_non_host_uri_content_not_emitted(self):
        for locator in ('data:text/plain,private-payload', 'mailto:private@example.test',
                        'https:/private-path', '//records.example.test/private-path'):
            with self.subTest(locator=locator):
                self.row['url'] = locator
                self.write_sources([self.row])
                report = self.report()
                self.assertEqual(report['verdict'], 'COMPLETE')
                emitted = json.dumps(report) + coverage.render_table(report)
                for private in ('private-payload', 'private@example.test', 'private-path', 'data:', 'mailto:'):
                    self.assertNotIn(private, emitted)

    def test_typed_key_error_and_no_url_leak_from_error(self):
        self.row.pop('url')
        self.write_sources([self.row])
        report = self.report()
        self.assertEqual(report['sources'][0]['error']['type'], 'KeyError')
        self.assertEqual(report['verdict'], 'INCOMPLETE')

    def test_resolver_error_urls_are_host_only(self):
        from skippercast.seafloor import rights
        with patch.object(rights, 'source_rights', side_effect=ValueError(
                'Unqualified https://user:password@example.test/private?q=secret#frag')):
            report = self.report()
        text = json.dumps(report) + coverage.render_table(report)
        self.assertEqual(report['verdict'], 'INCOMPLETE')
        self.assertEqual(report['sources'][0]['error']['type'], 'ValueError')
        self.assertIn('example.test', text)
        for forbidden in ('https:', 'password', '/private', 'q=secret', '#frag'):
            self.assertNotIn(forbidden, text)

    def test_uses_actual_resolver_without_schema_translation(self):
        from skippercast.seafloor import rights
        with patch.object(rights, 'source_rights', wraps=rights.source_rights) as call:
            self.report()
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[0], self.row)

    def test_empty_and_invalid_sources_refused(self):
        for slugs in ([], [None], ['../escape'], 'federal'):
            with self.subTest(slugs=slugs):
                self.write_recipe(slugs)
                with self.assertRaises(ValueError):
                    self.report()

    def test_duplicates_do_not_hide_other_sources(self):
        self.write_recipe(['federal', 'missing', 'federal'])
        report = self.report()
        self.assertEqual([r['slug'] for r in report['sources']], ['federal', 'missing'])
        self.assertEqual(report['lacking_rights'], ['missing'])

    def test_cli_new_output_and_no_overwrite(self):
        output = self.root / 'new-output'
        argv = ['--repo-root', str(self.root), '--recipe', str(self.recipe), '--output-root', str(output)]
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(coverage.main(argv), 0)
        self.assertIn('COMPLETE', stdout.getvalue())
        original = (output / 'coverage.json').read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(coverage.main(argv), 2)
        self.assertEqual((output / 'coverage.json').read_bytes(), original)

    def test_symlink_inputs_and_output_refused_before_read_or_write(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            coverage.check_coverage(alias, self.recipe)
        output = alias / 'output'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(coverage.main(['--repo-root', str(self.root), '--recipe', str(self.recipe),
                                           '--output-root', str(output)]), 2)
        self.assertFalse((self.root / 'output').exists())

    def test_catalog_nested_rights_are_not_silently_promoted(self):
        self.write_sources([{'id': 'federal', 'rights': {'license': 'public-domain', 'attribution': 'Credit'}}])
        report = self.report()
        self.assertEqual(report['verdict'], 'INCOMPLETE')
        self.assertEqual(report['sources'][0]['error']['type'], 'ValueError')

    def test_committed_morro_bay_records_actual_verdict(self):
        report = coverage.check_coverage(ROOT, ROOT / 'regions/morro-bay/coast.json')
        recipe = json.loads((ROOT / 'regions/morro-bay/coast.json').read_text())
        self.assertEqual([r['slug'] for r in report['sources']], recipe['sources'])
        expected = []
        from skippercast.seafloor.rights import source_rights
        catalog = json.loads((ROOT / 'catalog/sources.json').read_text())['sources']
        for slug in recipe['sources']:
            row = next(r for r in catalog if r['id'] == slug)
            try:
                rights = source_rights(copy.deepcopy(row))
                if not isinstance(rights.get('attribution'), str) or not rights['attribution'].strip():
                    expected.append(slug)
            except (ValueError, KeyError, TypeError):
                expected.append(slug)
        self.assertEqual(report['lacking_rights'], expected)
        print('MORRO_BAY_OBSERVATION ' + json.dumps(report, sort_keys=True))
