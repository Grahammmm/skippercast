"""The Text Advisor privacy scan in scripts/check_repository.py (TA-C5).

docs/plans/text-advisor/02-data-model.md § Privacy invariants: over
tests/fixtures/advisor/, docs/plans/text-advisor/ and the advisor runbooks, a
NANP number must be in the fictional 555 series and an Instagram handle must be
listed in catalog/advisor/fixture-handles.json. Numbers and handles that could be
real are assembled at run time, so this file never holds one either.
"""
import importlib.util
import json
from pathlib import Path, PurePosixPath
import tempfile
import unittest
from unittest import mock

from tests._support import ROOT


_spec = importlib.util.spec_from_file_location('check_repository', ROOT / 'scripts/check_repository.py')
check_repository = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_repository)

FIXTURE = PurePosixPath('tests/fixtures/advisor/meta/example.json')
PLAN = PurePosixPath('docs/plans/text-advisor/03-channels.md')
ALLOWED = {'skippercast', 'sea.example', 'handle'}
# Not in the fictional series: a 555 line outside 01XX, and an ordinary line (built, never written out).
REAL_555 = '+1' + '805' + '555' + '12' + '34'
REAL = '+1' + '805' + '772' + '00' + '00'
UNLISTED = 'some' + '.boat' + '_handle'


def scan(text, relative=PLAN, allowed=ALLOWED):
    return check_repository.advisor_privacy(relative, text, allowed)


class ScopeTests(unittest.TestCase):
    def test_fixtures_plan_and_advisor_runbooks_are_scanned(self):
        for name in ('tests/fixtures/advisor/twilio/inbound-text.json', 'docs/plans/text-advisor/README.md',
                     'docs/operations/runbooks/advisor-relay-setup.md'):
            with self.subTest(name):
                self.assertTrue(check_repository.advisor_scoped(PurePosixPath(name)))

    def test_other_files_are_not(self):
        for name in ('tests/fixtures/http/sample.json', 'docs/operations/runbooks/rollback-release.md',
                     'docs/operations/runbooks/advisor/notes.md', 'tests/test_advisor_contacts.mjs', 'server/advisor/contacts.ts'):
            with self.subTest(name):
                self.assertFalse(check_repository.advisor_scoped(PurePosixPath(name)))


class AdvisorTestFileTests(unittest.TestCase):
    """Hardening: the handle rule also covers tests/test_advisor_*.mjs (mentions and quoted handle fields)."""

    def test_scope(self):
        self.assertTrue(check_repository.advisor_test_file(PurePosixPath('tests/test_advisor_skippers.mjs')))
        for name in ('tests/test_accounts.mjs', 'tests/fixtures/test_advisor_x.mjs', 'tests/test_advisor_x.py'):
            with self.subTest(name):
                self.assertFalse(check_repository.advisor_test_file(PurePosixPath(name)))

    def test_listed_handles_pass(self):
        text = "addBoat(sql, {instagram: 'sea.example'}); caption('Follow @SkipperCast and @Sea.Example.'); collaborators: ['@sea.example', 'skippercast']"
        self.assertEqual(check_repository.advisor_test_handles(PurePosixPath('tests/test_advisor_x.mjs'), text, ALLOWED), [])

    def test_unlisted_handles_fail_without_naming_them(self):
        relative = PurePosixPath('tests/test_advisor_x.mjs')
        for text in (f"caption('aboard @{UNLISTED}')", f"addBoat(sql, {{instagram: '{UNLISTED}'}})", f'{{username: "@{UNLISTED}"}}',
                     f"post({{collaborators: ['sea.example', '{UNLISTED}']}})"):
            with self.subTest(text[:20]):
                errors = check_repository.advisor_test_handles(relative, 'first line\n' + text, ALLOWED)
                self.assertEqual(len(errors), 1)
                self.assertIn(f'{relative}:2: Instagram handle not in', errors[0])
                self.assertNotIn(UNLISTED, errors[0])

    def test_emails_paths_and_versions_are_not_handles(self):
        text = "mail@example.com, import('@scope/pkg'), 'claude-haiku-5@2026', instagram: null"
        self.assertEqual(check_repository.advisor_test_handles(PurePosixPath('tests/test_advisor_x.mjs'), text, ALLOWED), [])


class PhoneTests(unittest.TestCase):
    def test_fictional_series_passes(self):
        self.assertEqual(scan('call +15555550123, +15559876543, +18055550100 or +18055550199'), [])

    def test_numbers_outside_the_series_fail(self):
        for number in (REAL, REAL_555, '+1' + '805' + '555' + '02' + '00'):
            with self.subTest(number[-4:]):
                errors = scan(f'line one\nreach the skipper at {number} today')
                self.assertEqual(len(errors), 1)
                self.assertIn(f'{PLAN}:2: phone number outside the fictional 555 series', errors[0])

    def test_the_message_never_carries_the_number(self):
        (error,) = scan(f'"from": "{REAL}"', FIXTURE)
        self.assertNotIn(REAL, error)
        self.assertNotIn(REAL[2:], error)

    def test_separated_digits_and_other_countries_are_not_e164_nanp(self):
        self.assertEqual(scan('(805) 772-0000, 805-772-0000, +447700900123'), [])


class HandleTests(unittest.TestCase):
    def test_listed_mentions_pass_in_any_case_and_before_a_period(self):
        self.assertEqual(scan('Follow @SkipperCast. Tagged @Sea.Example. The boat\'s `@handle`.'), [])

    def test_an_unlisted_mention_fails_without_echoing_it(self):
        (error,) = scan(f'Thanks, tagged @{UNLISTED} on your posts.')
        self.assertIn('Instagram handle not in catalog/advisor/fixture-handles.json', error)
        self.assertNotIn(UNLISTED, error)

    def test_emails_paths_and_npm_scopes_are_not_handles(self):
        self.assertEqual(scan('mail owner@example.test; import @anthropic-ai/sdk and @block65/webcrypto-web-push; '
                              'see https://www.instagram.com/@x/ and a.b@c.d'), [])

    def test_one_character_mentions_are_ignored(self):
        self.assertEqual(scan('"Also aboard: @x." for handles past the three'), [])

    def test_json_handle_fields_are_checked_at_any_depth(self):
        listed = json.dumps({'data': [{'username': 'sea.example'}], 'boat': {'instagram': '@Sea.Example'},
                             'post': {'collaborators': ['skippercast']}})
        self.assertEqual(scan(listed, FIXTURE), [])
        for document in ({'username': UNLISTED}, {'boat': {'instagram': UNLISTED}}, {'post': {'collaborators': ['sea.example', UNLISTED]}},
                         {'value': {'from': {'id': '1', 'handle': UNLISTED}}}):
            with self.subTest(document):
                errors = scan(json.dumps(document), FIXTURE)
                self.assertEqual(errors, [f'{FIXTURE}: handle field value not in catalog/advisor/fixture-handles.json'])

    def test_other_json_fields_and_non_handles_are_not_handles(self):
        self.assertEqual(scan(json.dumps({'name': UNLISTED, 'text': 'Sea Example', 'username': 'Not A Handle!', 'instagram': None}), FIXTURE), [])

    def test_handle_fields_only_count_in_json(self):
        self.assertEqual(scan(f'"username": "{UNLISTED}"', PLAN), [])


class FixtureHandleListTests(unittest.TestCase):
    def test_the_committed_list_loads_and_every_fixture_handle_is_fictional(self):
        allowed, problems = check_repository.load_fixture_handles()
        self.assertEqual(problems, [])
        data = json.loads((ROOT / check_repository.FIXTURE_HANDLES).read_text(encoding='utf-8'))
        self.assertEqual(set(data['own']), {'skippercast'})
        self.assertTrue(all('example' in h or 'placeholder' in h for h in data['fictional']))
        self.assertTrue({'skippercast', 'sea.example', 'deckhand.example'} <= allowed)

    def test_a_real_looking_fictional_entry_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'catalog/advisor').mkdir(parents=True)
            (root / check_repository.FIXTURE_HANDLES).write_text(json.dumps({'own': {'skippercast': 'ours'},
                'fictional': {UNLISTED: 'looks real', 'Upper.Example': 'not lower case'}, 'placeholders': {}}))
            allowed, problems = check_repository.load_fixture_handles(root)
        self.assertEqual(allowed, {'skippercast'})
        self.assertEqual(len(problems), 2)
        self.assertTrue(all(UNLISTED not in p for p in problems))

    def test_a_missing_list_is_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(check_repository.load_fixture_handles(Path(tmp)), (set(), [f'{check_repository.FIXTURE_HANDLES}: missing or not JSON']))


class RepositoryTests(unittest.TestCase):
    def test_the_committed_fixtures_plan_and_runbooks_pass(self):
        allowed, _ = check_repository.load_fixture_handles()
        files = sorted(p for p in ROOT.rglob('*') if p.is_file() and check_repository.advisor_scoped(p.relative_to(ROOT))
                       and 'var' not in p.relative_to(ROOT).parts)
        self.assertGreater(len(files), 100, 'the fixtures, the plan and the runbooks are all found')
        errors = []
        for path in files:
            try:
                text = path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue   # the vision PNGs: pinned by hash in scripts/web-vendor-sha256.json
            errors += check_repository.advisor_privacy(path.relative_to(ROOT), text, allowed)
        self.assertEqual(errors, [])

    def test_main_fails_on_a_planted_number_and_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'catalog/advisor').mkdir(parents=True)
            (root / check_repository.FIXTURE_HANDLES).write_bytes((ROOT / check_repository.FIXTURE_HANDLES).read_bytes())
            (root / 'tests/fixtures/advisor/bluebubbles').mkdir(parents=True)
            (root / 'tests/fixtures/advisor/bluebubbles/text.json').write_text(json.dumps({'data': {'handle': {'address': '+15555550101'}}}))
            with mock.patch.object(check_repository, 'ROOT', root), mock.patch('sys.stderr') as err, mock.patch('sys.stdout'):
                self.assertEqual(check_repository.main(), 0)
                (root / 'tests/fixtures/advisor/bluebubbles/text.json').write_text(json.dumps({'data': {'handle': {'address': REAL}}, 'username': UNLISTED}))
                self.assertEqual(check_repository.main(), 1)
            printed = ''.join(str(call.args[0]) for call in err.write.call_args_list if call.args)
            self.assertIn('tests/fixtures/advisor/bluebubbles/text.json:1: phone number outside the fictional 555 series', printed)
            self.assertIn('handle field value not in', printed)
            self.assertNotIn(REAL, printed)
            self.assertNotIn(UNLISTED, printed)


if __name__ == '__main__':
    unittest.main()
