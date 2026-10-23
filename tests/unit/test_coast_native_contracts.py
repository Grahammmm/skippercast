"""No-GIS collection and structural checks for retained native wrappers."""
from copy import deepcopy
import pytest

from tests.coast_contract_factory import load_helper

validator = load_helper('validate_coast_receipt')
refs = load_helper('coast_refs')
HEADER = dict(created_utc='2026-10-21T00:00:00Z', author_profile='synthetic', author_model='offline-synthetic',
              card_id='t_0da2d434', code_commit='1'*40, skill_commit='2'*40)


@pytest.mark.parametrize('name', ['execution', 'rights-evidence'])
def test_native_wrapper_schema_roundtrip_and_unknown_ref_refusal(name):
    reference = dict(root_id='queue:synthetic', path='synthetic', sha256='0'*64, bytes=0)
    value = dict(schema='coast-native-' + name + '-v1', **HEADER)
    if name == 'execution':
        value.update(job=dict(reference, path='job.json'), result=dict(reference, path='result.json'),
                     logs=[dict(reference, path='stdout.log'), dict(reference, path='stderr.log')])
    else:
        value.update(statement='Synthetic only; no scientific acceptance', synthetic=True)
    validator.validate_schema(refs.loads(refs.canonical(value)))
    for mutation in ('self_sha256', 'unknown_path'):
        bad = dict(deepcopy(value), **{mutation: 'unadmitted'})
        with pytest.raises(ValueError, match='schema'):
            validator.validate_schema(bad)
    del value['author_model']
    with pytest.raises(ValueError, match='schema'):
        validator.validate_schema(value)


def test_checkout_cli_confines_target_and_pins_child_import(tmp_path):
    import subprocess
    import sys
    from tests.coast_contract_factory import ROOT, SCRIPTS
    runner = ROOT / 'tests/coast_checkout_cli.py'
    good = subprocess.run([sys.executable, str(runner), str(SCRIPTS / 'validate_coast_receipt.py'),
        '--hash-dir', str(tmp_path)], capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
    assert refs.loads(good.stdout) == []  # runner checked child package origin first
    foreign = tmp_path / 'foreign-checkout.py'
    foreign.write_text("raise AssertionError('foreign checkout executed')\n")
    bad = subprocess.run([sys.executable, str(runner), str(foreign)], capture_output=True, text=True)
    assert bad.returncode != 0
    assert 'inside this checkout' in bad.stderr
    assert 'foreign checkout executed' not in bad.stderr
