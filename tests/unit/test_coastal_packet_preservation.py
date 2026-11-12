"""build_acquisition_package must refuse any already-present output entry, even a dangling link.

The real builder runs on the synthetic candidate-document fixture; nothing is mocked
except a spy on the shared writer, used to prove refusal happens before any write.
"""
import os
from unittest import mock

import pytest

from skippercast.coastal.coordinator import packet_release
from skippercast.coastal.handoff.common import ref, write
from tests.contract.test_four128_candidate_documents import candidate_documents

PREFIX = 'probe'
SLOTS = [f'{PREFIX}-0.json', f'{PREFIX}-1.json', f'{PREFIX}-2.json', f'{PREFIX}-3.json',
         f'{PREFIX}-validation.json']


def _setup(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    grant, templates, documents = candidate_documents(root, False)

    def put(name, doc):
        path = root / 'metadata' / (name + '.json')
        write(path, doc)
        return ref(root, path, doc['schema'])

    roles = {name: put(name, doc) for name, doc in documents.items()}
    grant_ref = put('grant', grant)
    template_refs = [put(f'template-{i}', t) for i, t in enumerate(templates)]
    return root, grant, grant_ref, template_refs, roles


def _build(root, grant_ref, template_refs, roles):
    return packet_release.build_acquisition_package(
        root, grant_ref, template_refs, rights=[roles['rights']], trial=roles['trial'],
        segment=roles['segment'], now=100, horizon=3700, prefix=PREFIX)


def _inventory(root):
    """Every entry under root without following links: link text, lstat identity, file bytes."""
    rows = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            st = os.lstat(path)
            key = os.path.relpath(path, root)
            if os.path.islink(path):
                rows[key] = ('link', os.readlink(path), st.st_ino)
            elif os.path.isdir(path):
                rows[key] = ('dir', st.st_ino)
            else:
                with open(path, 'rb') as handle:
                    rows[key] = ('file', handle.read(), st.st_ino)
    return rows


def _refuse(root, grant_ref, template_refs, roles):
    before = _inventory(root)
    with mock.patch.object(packet_release, 'write', wraps=packet_release.write) as spy:
        with pytest.raises(ValueError, match='preserve existing packet package'):
            _build(root, grant_ref, template_refs, roles)
    assert spy.call_count == 0
    assert _inventory(root) == before


def _plant(root, slot, kind, tmp_path):
    path = root / 'metadata' / slot
    if kind == 'dangling':
        path.symlink_to(tmp_path / 'never-created.json')
    elif kind == 'file':
        path.write_bytes(b'preserve me\n')
    elif kind == 'directory':
        path.mkdir()
    elif kind == 'link_to_file':
        (tmp_path / 'real-target.json').write_bytes(b'real target\n')
        path.symlink_to(tmp_path / 'real-target.json')
    elif kind == 'link_to_directory':
        (tmp_path / 'real-dir').mkdir()
        path.symlink_to(tmp_path / 'real-dir')
    return path


def test_dangling_first_candidate_preserved(tmp_path):
    root, _, grant_ref, templates, roles = _setup(tmp_path)
    link = _plant(root, SLOTS[0], 'dangling', tmp_path)
    literal = os.readlink(link)
    inode = os.lstat(link).st_ino
    _refuse(root, grant_ref, templates, roles)
    assert os.path.islink(link) and os.readlink(link) == literal
    assert os.lstat(link).st_ino == inode
    assert not (tmp_path / 'never-created.json').exists()
    assert sorted(p.name for p in (root / 'metadata').glob(PREFIX + '*')) == [SLOTS[0]]


@pytest.mark.parametrize('slot', SLOTS[1:4])
def test_dangling_later_candidate_refuses_before_first_write(tmp_path, slot):
    root, _, grant_ref, templates, roles = _setup(tmp_path)
    link = _plant(root, slot, 'dangling', tmp_path)
    _refuse(root, grant_ref, templates, roles)
    assert os.path.islink(link)
    assert sorted(p.name for p in (root / 'metadata').glob(PREFIX + '*')) == [slot]


def test_dangling_validation_receipt_preserved(tmp_path):
    root, _, grant_ref, templates, roles = _setup(tmp_path)
    link = _plant(root, SLOTS[4], 'dangling', tmp_path)
    _refuse(root, grant_ref, templates, roles)
    assert os.path.islink(link)
    assert sorted(p.name for p in (root / 'metadata').glob(PREFIX + '*')) == [SLOTS[4]]
    assert not (tmp_path / 'never-created.json').exists()


@pytest.mark.parametrize('slot', [SLOTS[0], SLOTS[3], SLOTS[4]])
@pytest.mark.parametrize('kind', ['file', 'directory', 'link_to_file', 'link_to_directory'])
def test_existing_entry_matrix_retains_refusal(tmp_path, slot, kind):
    root, _, grant_ref, templates, roles = _setup(tmp_path)
    _plant(root, slot, kind, tmp_path)
    _refuse(root, grant_ref, templates, roles)
    assert sorted(p.name for p in (root / 'metadata').glob(PREFIX + '*')) == [slot]


def test_absent_outputs_still_build_full_held_package(tmp_path):
    root, grant, grant_ref, templates, roles = _setup(tmp_path)
    result = _build(root, grant_ref, templates, roles)
    assert result['status'] == 'PASS_METADATA_ONLY'
    assert len(result['requests']) == 4
    assert sorted(p.name for p in (root / 'metadata').glob(PREFIX + '*')) == sorted(SLOTS)
    for entry in [*result['requests'], result['validation']]:
        assert (root / entry['path']).is_file()
    assert result['execution_authorized'] is False
    assert result['native_operations'] == 0
    assert result['Store_created'] is False
    assert result['Budget_created'] is False
    assert result['unit_clock_created'] is False
    assert not os.path.exists(grant['source_root'])
    assert not os.path.exists(grant['output_root'])


def test_independent_retry_after_caller_removes_obstruction(tmp_path):
    root, _, grant_ref, templates, roles = _setup(tmp_path)
    link = _plant(root, SLOTS[1], 'dangling', tmp_path)
    _refuse(root, grant_ref, templates, roles)
    link.unlink()
    assert _build(root, grant_ref, templates, roles)['status'] == 'PASS_METADATA_ONLY'
