"""Missing-reviewer regression for the installed t08a supersedes() helper (synthetic fixtures)."""
import copy
import hashlib

import pytest

import supersedes_fixture as fx

DOC = 'doc'
VALID = '2026-01-01T00:00:00+00:00'


def build(tmp_path, entry, mutate=False):
    prior = fx.write_prior(tmp_path)
    fn = fx.parse_helper()
    if mutate:
        mutant = fx.DirectIndexMutant()
        fn = mutant.visit(copy.deepcopy(fn))
        assert mutant.count == 1
    return fx.compile_helper(fn, prior, {DOC: entry}), prior


def test_absent_reviewer_id_returns_none_without_keyerror(tmp_path):
    helper, prior = build(tmp_path, {'valid_until': VALID})
    out = helper(DOC)
    assert 'reviewer_id' in out and out['reviewer_id'] is None
    assert out['valid_until'] == VALID
    assert out['path'] == str(prior / 'metadata' / 'doc.json')


@pytest.mark.parametrize('value', [None, '', 'rev-1'])
def test_null_empty_and_present_reviewer_id_are_preserved(tmp_path, value):
    helper, _ = build(tmp_path, {'valid_until': VALID, 'reviewer_id': value})
    assert helper(DOC)['reviewer_id'] == value


def test_absent_valid_until_remains_a_required_field_failure(tmp_path):
    helper, _ = build(tmp_path, {'reviewer_id': 'rev-1'})
    with pytest.raises(KeyError, match='valid_until'):
        helper(DOC)


def test_unknown_document_name_fails(tmp_path):
    helper, prior = build(tmp_path, {'valid_until': VALID})
    # The prior-document hash is read first, so a name with no prior file fails there.
    with pytest.raises(FileNotFoundError):
        helper('no-such-doc')
    # A name whose prior file exists but has no expired entry fails the required lookup.
    (prior / 'metadata' / 'orphan.json').write_text('{}', encoding='utf-8')
    with pytest.raises(KeyError, match='orphan'):
        helper('orphan')


def test_changed_json_bytes_change_the_actual_hash(tmp_path):
    helper, prior = build(tmp_path, {'valid_until': VALID})
    target = prior / 'metadata' / 'doc.json'
    before = helper(DOC)['sha256']
    assert before == hashlib.sha256(target.read_bytes()).hexdigest()
    target.write_text('{"synthetic": "changed"}', encoding='utf-8')
    after = helper(DOC)['sha256']
    assert after != before and after == hashlib.sha256(target.read_bytes()).hexdigest()


def test_old_direct_index_mutant_fails_the_missing_field_case(tmp_path):
    helper, _ = build(tmp_path, {'valid_until': VALID}, mutate=True)
    with pytest.raises(KeyError, match='reviewer_id'):
        helper(DOC)


def test_ambiguous_missing_and_drifted_sources_refuse(tmp_path):
    src = fx.SNAPSHOT.read_text(encoding='utf-8')
    cases = {
        'ambiguous': src + '\n' + src,
        'missing': src.replace('def supersedes', 'def other'),
        'toplevel': 'import os\n' + src,
    }
    for name, text in cases.items():
        path = tmp_path / (name + '.py')
        path.write_text(text, encoding='utf-8')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with pytest.raises(ValueError):
            fx.parse_helper(path, digest)
    drift = tmp_path / 'drift.py'
    drift.write_text(src + '# drift\n', encoding='utf-8')
    with pytest.raises(ValueError, match='digest'):
        fx.parse_helper(drift)
    assert fx.parse_helper().name == 'supersedes'
