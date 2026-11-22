"""Exercise the real offline handoff CLI with synthetic plan and input files."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests._support import ROOT


def _cli(command, plan, inputs, *options):
    argv = [sys.executable, str(ROOT / 'scripts/relief/rebuild_plan_stamp.py'),
            command, '--plan', str(plan), *options]
    for role, path in inputs:
        argv.extend(('--input', f'{role}={path}'))
    return subprocess.run(argv, capture_output=True, timeout=10)


@pytest.fixture
def handoff(tmp_path):
    plan = tmp_path / 'proposal.json'
    plan.write_bytes(b'{"stages": []}\n')
    style, config = tmp_path / 'style', tmp_path / 'config'
    style.write_bytes(b'fixture style\x00\xff')
    config.write_bytes(b'fixture config\r\n')
    inputs = [('style', style), ('config', config)]
    emitted = _cli('emit', plan, inputs)
    assert emitted.returncode == 0, emitted.stderr
    stamp = tmp_path / 'handoff.json'
    stamp.write_bytes(emitted.stdout)
    return plan, inputs, stamp


def test_unchanged_copies_validate_after_relocation(handoff, tmp_path):
    # Path/mtime pins or insertion-ordered roles would reject this intact handoff.
    plan, inputs, stamp = handoff

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    assert json.loads(stamp.read_bytes()) == {
        'format': 'rebuild-plan-stamp/v1',
        'plan_sha256': digest(plan),
        'inputs': [['config', digest(inputs[1][1])], ['style', digest(inputs[0][1])]],
    }
    relocated = tmp_path / 'relocated'
    relocated.mkdir()

    def copy(path: Path) -> Path:
        target = relocated / f'copied-{path.name}'
        shutil.copyfile(path, target)
        return target

    result = _cli('verify', copy(plan), [(role, copy(path)) for role, path in reversed(inputs)],
                  '--stamp', str(copy(stamp)))
    assert result.returncode == 0, result.stderr


def test_changed_plan_bytes_fail_with_same_inputs(handoff):
    # Ignoring the plan or reserializing its JSON would bless a changed proposal.
    plan, inputs, stamp = handoff
    plan.write_bytes(b'{"stages":[]}\n')
    result = _cli('verify', plan, inputs, '--stamp', str(stamp))
    assert result.returncode == 1, result.stderr


def test_swapped_roles_fail_with_same_digest_multiset(handoff):
    # Hashing just the set (or sorted list) of digests would bless this swap.
    plan, inputs, stamp = handoff
    (first, first_path), (second, second_path) = inputs
    result = _cli('verify', plan, [(first, second_path), (second, first_path)],
                  '--stamp', str(stamp))
    assert result.returncode == 1, result.stderr


def test_duplicate_role_is_not_silently_overwritten(handoff):
    # A last-value-wins map would silently discard an explicit input assignment.
    plan, inputs, _ = handoff
    result = _cli('emit', plan, [*inputs, (inputs[0][0], inputs[1][1])])
    assert result.returncode == 2
    assert b'duplicate input role' in result.stderr
    assert result.stdout == b''
