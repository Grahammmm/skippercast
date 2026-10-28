"""SC38: coast prefetch plans need an integer schema_version of exactly 1.

``load_plan`` used to compare ``schema_version != 1`` only, so JSON ``true`` and
``1.0``/``1e0`` were accepted as version 1. These tests read real JSON plan
files through the complete ``prefetch.load_plan`` with an explicitly supplied
offline Session (synthetic exact allowlist, no resolver, no connection, no
requests). They never construct ``Prefetch`` or call a run/preflight/transfer
method: the isolation fixture redirects every module path constant and bound
default under ``tmp_path`` and makes the transfer constructors and the network
raise. See docs/engineering/sc38_prefetch_version.md.
"""
import hashlib
import inspect
import json
import socket
import textwrap

import pytest

from skippercast.coastal import prefetch as p
from skippercast.http import Session
from tests._support import FIXTURES

FIXTURE_DIR = FIXTURES / 'sc38_prefetch_version'
HOLD_MESSAGE = 'Expected schema_version=1 and files array'
VERSION_LINE = '"schema_version": 1,'
HOST = 'data.ngdc.noaa.gov'
SURVEY = 'https://data.ngdc.noaa.gov/sc38/survey.bag'
OTHER = SURVEY + '?other'

# The submitted gate and the baseline (equality-only) gate, as they appear in load_plan.
TYPE_GATE = "type(plan.get('schema_version')) is not int or "
BASELINE_LINE = "    if plan.get('schema_version') != 1 or not isinstance(plan.get('files'), list):\n"
# sha256 of inspect.getsource(load_plan) at base 59fca09b (prefetch.py cb39907b...).
BASELINE_LOAD_PLAN_SHA256 = '4d707dfac6e88679b30f704269f032792bca858314c627cc73ab2d78cd7a0a5f'

# JSON tokens substituted for the literal ``1`` of the fixture's version line.
REJECTED_TOKENS = {
    'true': 'true', 'false': 'false', 'float-1.0': '1.0', 'exponent-1e0': '1e0',
    'string-1': '"1"', 'null': 'null', 'object': '{}', 'object-1': '{"major": 1}',
    'list': '[]', 'list-1': '[1]', 'zero': '0', 'two': '2', 'negative-1': '-1',
}
# The baseline gate accepted exactly these; the mutation controls must catch each one.
MUTATION_TOKENS = {'true': 'true', 'float-1.0': '1.0', 'exponent-1e0': '1e0'}


class Refused(AssertionError):
    """A transfer, network or default-allowlist path was reached in an input-only test."""


def refuse(*args, **kwargs):
    raise Refused('network/transfer path reached in an SC38 input-plan test')


class SpySession(Session):
    """The real policy Session with an explicit synthetic allowlist, recording check_url.

    No resolver, connection factory, proxy or cache can be used: each raises.
    ``check_url`` is the genuine pure policy check (no DNS); the spy only records it.
    """

    def __init__(self):
        super().__init__(allowed_hosts=[HOST], resolver=refuse, connection_factory=refuse,
                         proxies={}, attempts=1, cache=None, sleep=refuse)
        self.checked = []

    def check_url(self, url, *args, **kwargs):
        self.checked.append(url)
        return super().check_url(url, *args, **kwargs)

    def request(self, *args, **kwargs):
        refuse()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Redirect module paths and bound defaults; block network and transfer constructors."""
    root = tmp_path / 'isolated'
    paths = dict(MOUNT=root / 'mount', RAW=root / 'mount/raw', MIRROR=root / 'mirror',
                 RETRY_STATE=root / 'mirror/retry-state.json', STATUS=root / 'status.json')
    for name, value in paths.items():
        monkeypatch.setattr(p, name, value)
    original_init = p.Prefetch.__init__
    defaults = dict(original_init.__kwdefaults__)
    defaults.update(root=paths['RAW'], mirror=paths['MIRROR'], status=paths['STATUS'], mount=paths['MOUNT'])
    monkeypatch.setattr(original_init, '__kwdefaults__', defaults)
    monkeypatch.setattr(p.Prefetch, '__init__', refuse)
    monkeypatch.setattr(p.TransferSession, '__init__', refuse)
    monkeypatch.setattr(p, 'default_allowlist', refuse)
    monkeypatch.setattr(socket, 'getaddrinfo', refuse)
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    return dict(root=root, paths=paths, original_init=original_init)


@pytest.fixture
def filename_calls(monkeypatch):
    """Count normalization: load_plan calls filename() once per accepted unique URL."""
    calls = []
    genuine = p.filename

    def spy(row):
        calls.append(row['url'])
        return genuine(row)
    monkeypatch.setattr(p, 'filename', spy)
    return calls


def fixture_text(name):
    return (FIXTURE_DIR / name).read_text(encoding='utf-8')


def staged_plan(tmp_path, token=None, *, absent=False, name='valid-plan.json'):
    """Write a real JSON plan file, optionally with a different version token or none."""
    text = fixture_text(name)
    if absent or token is not None:
        assert text.count(VERSION_LINE) == 1
        text = text.replace(VERSION_LINE, '' if absent else VERSION_LINE.replace('1', token))
    inputs = tmp_path / 'input'
    inputs.mkdir(exist_ok=True)
    path = inputs / 'plan.json'
    path.write_text(text, encoding='utf-8')
    return path


def tree(path):
    return sorted(str(p.relative_to(path)) for p in path.rglob('*'))


def assert_held_before_io(tmp_path, path, session, filename_calls, loader=None):
    before_bytes, before_tree = path.read_bytes(), tree(tmp_path)
    with pytest.raises(p.Hold) as caught:
        (loader or p.load_plan)(path, session)
    assert str(caught.value) == HOLD_MESSAGE
    assert session.checked == [], 'check_url ran before the version hold'
    assert filename_calls == [], 'normalization ran before the version hold'
    assert path.read_bytes() == before_bytes
    assert tree(tmp_path) == before_tree, 'output written before the version hold'


# ---- isolation boundary ---------------------------------------------------------------

def test_isolation_redirects_paths_and_blocks_transfer(tmp_path, isolated):
    for name, value in isolated['paths'].items():
        assert getattr(p, name) == value and str(value).startswith(str(tmp_path))
    assert p.Prefetch.__init__ is refuse and p.TransferSession.__init__ is refuse
    for key in ('root', 'mirror', 'status', 'mount'):
        assert str(isolated['original_init'].__kwdefaults__[key]).startswith(str(tmp_path))
    with pytest.raises(Refused):
        p.Prefetch({}, SpySession())
    with pytest.raises(Refused):
        p.TransferSession(allowed_hosts=[HOST])
    with pytest.raises(Refused):
        p.default_allowlist()
    with pytest.raises(Refused):
        socket.getaddrinfo(HOST, 443)
    with pytest.raises(Refused):
        SpySession().request('GET', SURVEY)


# ---- A1 valid and boundary behaviour ---------------------------------------------------

def test_a1_integer_version_plan_loads_and_dry_run_totals_are_preserved(tmp_path, filename_calls):
    session = SpySession()
    path = staged_plan(tmp_path)
    before = path.read_bytes()
    plan = p.load_plan(path, session)
    assert type(plan['schema_version']) is int and plan['schema_version'] == 1
    assert session.checked == [SURVEY, SURVEY, OTHER]
    assert [row['url'] for row in plan['files']] == [OTHER, SURVEY]
    assert plan['files'][1]['segments'] == ['C2', 'N7']  # duplicate-URL segment union
    assert sorted(filename_calls) == [SURVEY, OTHER]
    report = p.dry_run(plan)
    assert report['schema_version'] == 1 and report['review_required'] is True
    assert report['inventory_complete'] is True and report['unresolved'] == []
    assert len(report['files']) == 2
    assert report['segments']['C1'] == {'files': 1, 'known_bytes': 0, 'unknown_size_files': 1, 'total_bytes': None}
    assert report['segments']['C2'] == {'files': 1, 'known_bytes': 10, 'unknown_size_files': 0, 'total_bytes': 10}
    assert report['segments']['N7'] == {'files': 0, 'known_bytes': 0, 'unknown_size_files': 0, 'total_bytes': 0}
    assert path.read_bytes() == before
    assert tree(tmp_path) == ['input', 'input/plan.json']


def test_a1_conflicting_duplicate_still_refused_with_integer_version(tmp_path):
    session = SpySession()
    path = staged_plan(tmp_path, name='conflicting-duplicate.json')
    with pytest.raises(p.Hold, match='Conflicting duplicate URL'):
        p.load_plan(path, session)
    assert session.checked == [SURVEY, SURVEY]


# ---- A2 malformed versions are held before check_url, normalization and output ---------

@pytest.mark.parametrize('token', list(REJECTED_TOKENS.values()), ids=list(REJECTED_TOKENS))
def test_a2_non_integer_or_wrong_version_is_held_before_io(tmp_path, token, filename_calls):
    path = staged_plan(tmp_path, token)
    assert VERSION_LINE.replace('1', token) in path.read_text()
    assert_held_before_io(tmp_path, path, SpySession(), filename_calls)


def test_a2_absent_version_is_held_before_io(tmp_path, filename_calls):
    path = staged_plan(tmp_path, absent=True)
    assert 'schema_version' not in json.loads(path.read_text())
    assert_held_before_io(tmp_path, path, SpySession(), filename_calls)


def test_a2_decoded_bool_and_float_versions_are_the_cases_baseline_missed(tmp_path):
    # Python equality is why the baseline accepted them: True == 1.0 == 1.
    decoded = {name: json.loads(staged_plan(tmp_path, token).read_text())['schema_version']
               for name, token in MUTATION_TOKENS.items()}
    assert decoded == {'true': True, 'float-1.0': 1.0, 'exponent-1e0': 1.0}
    assert all(value == 1 and type(value) is not int for value in decoded.values())


def test_a2_files_array_check_is_independent_of_a_valid_version(tmp_path, filename_calls):
    inputs = tmp_path / 'input'
    inputs.mkdir()
    path = inputs / 'plan.json'
    path.write_text(json.dumps({'schema_version': 1, 'files': {'not': 'a list'}, 'unresolved': []}))
    assert_held_before_io(tmp_path, path, SpySession(), filename_calls)


def test_a2_empty_plan_hold_is_independent_of_a_valid_version(tmp_path, filename_calls):
    session = SpySession()
    path = staged_plan(tmp_path, name='empty-files.json')
    with pytest.raises(p.Hold, match='Empty inventory is not a completed campaign'):
        p.load_plan(path, session)
    assert session.checked == [] and filename_calls == []


# ---- A3 decisive synthetic mutation ------------------------------------------------------

def baseline_mutant():
    """The submitted load_plan with only the type gate removed: the baseline function.

    Built in-process from the genuine function source by one exact textual
    reversion; the production file is not edited. The result must hash to the
    recorded baseline load_plan source, so it is the original equality-only gate
    applied to the complete function.
    """
    source = inspect.getsource(p.load_plan)
    assert source.count(TYPE_GATE) == 1, 'submitted type gate not found exactly once'
    reverted = source.replace(TYPE_GATE, '')
    assert BASELINE_LINE in reverted
    assert hashlib.sha256(reverted.encode()).hexdigest() == BASELINE_LOAD_PLAN_SHA256
    namespace = dict(vars(p))
    exec(compile(textwrap.dedent(reverted), f'{p.__file__}#sc38-baseline-mutant', 'exec'), namespace)
    return namespace['load_plan']


@pytest.mark.parametrize('token', list(MUTATION_TOKENS.values()) + ['1'],
                         ids=[*MUTATION_TOKENS, 'healthy-integer-1'])
def test_mutation_controls(tmp_path, token, filename_calls):
    mutant = baseline_mutant()
    path = staged_plan(tmp_path, token)
    if token == '1':
        # Healthy control: both gates accept integer 1 with identical normalized output.
        genuine = p.load_plan(path, SpySession())
        assert mutant(path, SpySession()) == genuine
        assert genuine['schema_version'] == 1 and type(genuine['schema_version']) is int
        return
    # Deciding gate: the submitted function holds before check_url and normalization ...
    assert_held_before_io(tmp_path, path, SpySession(), filename_calls)
    # ... while the baseline gate accepts the same complete input, so the identical
    # rejection assertion fails (pytest's Failed, not an unrelated swallowed error).
    session = SpySession()
    accepted = mutant(path, session)
    assert accepted['schema_version'] == 1 and type(accepted['schema_version']) is not int
    assert session.checked == [SURVEY, SURVEY, OTHER]
    with pytest.raises(pytest.fail.Exception):
        assert_held_before_io(tmp_path, path, SpySession(), [], loader=mutant)
