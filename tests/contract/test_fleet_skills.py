"""The charter fleet skills name only commands, workflow inputs and runbooks that exist (N8).

The registry/activity workflows and the separate local schedule-evidence CLI are
prose an
agent follows on the data runner's host. A renamed CLI step, flag, workflow input or
runbook would break them silently, so every `python -m skippercast.fleet ...` and
`python -m skippercast.fleet.ais ...` they name is checked against the real parsers,
every `gh workflow run <file> -f <input>=` against the workflow's dispatch inputs, and
every runbook path against docs/operations/runbooks. The skills carry no registry data:
no email, phone number, 9-digit number (an MMSI) or URL outside the allowed hosts.
"""
import contextlib
import io
import re
import subprocess
import sys
import unittest

from skippercast.fleet import cli
from skippercast.fleet.ais.__main__ import COMMANDS as AIS_COMMANDS, main as ais_main
from tests._support import ROOT

SKILLS = ('skippercast-fleet-registry', 'skippercast-fleet-activity', 'skippercast-fleet-schedule-evidence')
SCHEDULE_SCRIPT = ROOT / 'scripts' / 'fleet' / 'schedule_evidence.py'
WORKFLOWS = ROOT / '.github' / 'workflows'
RUNBOOKS = ROOT / 'docs' / 'operations' / 'runbooks'
ALLOWED_HOSTS = ('github.com', 'skippercast.com', 'wildlife.ca.gov', 'marinecadastre.gov')

COMMAND = re.compile(r'python -m skippercast\.fleet(\.ais)? ([a-z-]+)([^`\n]*)')
SHORT_AIS = re.compile(r'`ais ([a-z-]+)')
FLAG = re.compile(r'(?<![\w-])--[a-z][a-z-]*')
DISPATCH = re.compile(r'gh workflow run ([a-z0-9-]+\.yml)([^`\n]*)')
INPUT = re.compile(r'(?<![\w-])-f ([a-z_]+)=')
WORKFLOW_FILE = re.compile(r'(?<![\w/.-])([a-z0-9-]+\.yml)\b')
RUNBOOK = re.compile(r'runbooks/([a-z0-9-]+\.md)')
URL = re.compile(r'https?://([^/\s`)>\]]+)')
EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
PHONE = re.compile(r'(?<![\w-])(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)')
NINE_DIGITS = re.compile(r'(?<!\d)\d{9}(?!\d)')


def skill_text(name):
    return (ROOT / 'skills' / name / 'SKILL.md').read_text(encoding='utf-8')


def front_matter(text):
    """The `key: value` pairs between the opening and closing `---` lines."""
    if not text.startswith('---\n') or '\n---\n' not in text[4:]:
        return {}
    block = text[4:].split('\n---\n', 1)[0]
    return dict(line.split(': ', 1) for line in block.splitlines() if ': ' in line)


def interface(path):
    """The `interface:` keys of an agents/openai.yaml (one level, quoted string values)."""
    lines = path.read_text(encoding='utf-8').splitlines()
    if 'interface:' not in lines:
        return {}
    values = {}
    for line in lines[lines.index('interface:') + 1:]:
        match = re.fullmatch(r'  ([a-z_]+): "(.*)"', line)
        if not match:
            break
        values[match.group(1)] = match.group(2)
    return values


def dispatch_inputs(path):
    """The workflow_dispatch input names of a workflow file."""
    lines = path.read_text(encoding='utf-8').splitlines()
    if '  workflow_dispatch:' not in lines:
        return None
    at = lines.index('  workflow_dispatch:') + 1
    if at >= len(lines) or lines[at] != '    inputs:':
        return set()
    names = set()
    for line in lines[at + 1:]:
        if line.strip() and not line.startswith('      '):
            break
        match = re.fullmatch(r'      ([a-z_]+):', line)
        if match:
            names.add(match.group(1))
    return names


def help_text(main, argv):
    """What a parser prints for `argv + ['--help']` (argparse exits after printing)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            main([*argv, '--help'])
        except SystemExit:
            pass
    return out.getvalue()


def fleet_steps():
    """The step choices of `python -m skippercast.fleet`, from its own parser."""
    usage = help_text(cli.main, []).split('positional arguments:', 1)[1]
    return set(re.search(r'\{([a-z,-]+)\}', usage).group(1).split(','))


class FleetSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.texts = {name: skill_text(name) for name in SKILLS}
        cls.steps = fleet_steps()

    def test_front_matter_names_the_folder(self):
        for name, text in self.texts.items():
            with self.subTest(name):
                meta = front_matter(text)
                self.assertEqual(meta.get('name'), name)
                self.assertTrue(meta.get('description', '').strip())

    def test_openai_yaml_has_a_display_name(self):
        for name in SKILLS:
            with self.subTest(name):
                values = interface(ROOT / 'skills' / name / 'agents' / 'openai.yaml')
                self.assertTrue(values.get('display_name'))
                self.assertTrue(values.get('short_description'))
                self.assertIn(f'${name}', values.get('default_prompt', ''))

    def test_parsers_list_the_steps_the_skills_rely_on(self):
        self.assertIn('report', self.steps)
        self.assertIn('watch-check', AIS_COMMANDS)

    def test_every_named_command_and_flag_exists(self):
        for name, text in self.texts.items():
            commands = COMMAND.findall(text)
            if name == 'skippercast-fleet-schedule-evidence':
                self.assertTrue(SCHEDULE_SCRIPT.is_file())
                usage = subprocess.run([sys.executable, str(SCHEDULE_SCRIPT), '--help'], check=True,
                                       capture_output=True, text=True).stdout
                for flag in FLAG.findall(text):
                    with self.subTest(skill=name, flag=flag):
                        self.assertIn(flag, usage)
                continue
            self.assertTrue(commands, name)
            for ais, step, rest in commands:
                with self.subTest(skill=name, command=f'{ais} {step}'):
                    if ais:
                        self.assertIn(step, AIS_COMMANDS)
                        sub = rest.split()[:1] if step == 'label' else []
                        usage = help_text(ais_main, [step, *sub])
                    else:
                        self.assertIn(step, self.steps)
                        usage = help_text(cli.main, [step])
                    for flag in FLAG.findall(rest):
                        self.assertRegex(usage, rf'(?<![\w-]){re.escape(flag)}(?![\w-])', f'{step} has no {flag}')
            for step in SHORT_AIS.findall(text):
                with self.subTest(skill=name, short=step):
                    self.assertIn(step, AIS_COMMANDS)

    def test_every_named_workflow_and_input_exists(self):
        inputs = {path.name: dispatch_inputs(path) for path in WORKFLOWS.glob('*.yml')}
        every = set().union(*(names for names in inputs.values() if names))
        for name, text in self.texts.items():
            for workflow in WORKFLOW_FILE.findall(text):
                with self.subTest(skill=name, workflow=workflow):
                    self.assertIn(workflow, inputs)
            for workflow, rest in DISPATCH.findall(text):
                with self.subTest(skill=name, dispatch=workflow):
                    self.assertIsNotNone(inputs.get(workflow), f'{workflow} has no workflow_dispatch')
                    self.assertLessEqual(set(INPUT.findall(rest)), inputs[workflow])
            for value in INPUT.findall(text):
                with self.subTest(skill=name, input=value):
                    self.assertIn(value, every)

    def test_every_named_runbook_exists(self):
        for name, text in self.texts.items():
            runbooks = RUNBOOK.findall(text)
            self.assertTrue(runbooks, name)
            for runbook in runbooks:
                with self.subTest(skill=name, runbook=runbook):
                    self.assertTrue((RUNBOOKS / runbook).is_file())

    def test_no_contact_data_or_identifiers(self):
        for name in SKILLS:
            folder = ROOT / 'skills' / name
            for path in [folder / 'SKILL.md', folder / 'agents' / 'openai.yaml']:
                text = path.read_text(encoding='utf-8')
                with self.subTest(path=path.relative_to(ROOT).as_posix()):
                    self.assertEqual(EMAIL.findall(text), [])
                    self.assertEqual(PHONE.findall(text), [])
                    self.assertEqual(NINE_DIGITS.findall(text), [])
                    for host in URL.findall(text):
                        self.assertTrue(any(host == allowed or host.endswith('.' + allowed) for allowed in ALLOWED_HOSTS),
                                        f'URL host outside {ALLOWED_HOSTS}')

    def test_the_checks_catch_what_they_guard(self):
        self.assertEqual(front_matter('---\nname: x\ndescription: y\n---\n# x\n'), {'name': 'x', 'description': 'y'})
        self.assertTrue(PHONE.search('call (805) 555-0100'))
        self.assertTrue(EMAIL.search('skipper@example.org'))
        self.assertTrue(NINE_DIGITS.search('id 123456789 seen'))
        self.assertFalse(NINE_DIGITS.search('2026-10-12 and 1234567890'))
        self.assertFalse(PHONE.search('from 2026-01-01 to 2026-06-30'))
        self.assertNotIn('no-such-step', self.steps)


if __name__ == '__main__':
    unittest.main()
