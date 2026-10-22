"""Synthetic publication receipt controls; filenames carry no authority."""
import hashlib
import json
import os

import pytest

from research.scripts.mapping_claim_guard import GuardError, validate_checkpoint


def make_checkpoint(tmp_path):
    job = dict(id='job-1', state='published', owner='synthetic', dispatch_state='queued',
               output_path='out/job-1', receipt_paths=[], receipt_sha256={})
    for role in ('rights', 'restriction', 'live_readback'):
        name = role + '.json'
        raw = json.dumps(dict(schema='mapping-publication-receipt-v1', role=role,
                              status='PASS', job_id=job['id'])).encode()
        (tmp_path / name).write_bytes(raw)
        job['receipt_paths'].append(name)
        job['receipt_sha256'][name] = hashlib.sha256(raw).hexdigest()
    return dict(coordinator='synthetic-coordinator', jobs=[job])


def replace_doc(tmp_path, checkpoint, value):
    raw = json.dumps(value).encode()
    (tmp_path / 'restriction.json').write_bytes(raw)
    checkpoint['jobs'][0]['receipt_sha256']['restriction.json'] = hashlib.sha256(raw).hexdigest()


def test_valid_receipts_are_content_bound_not_filename_bound(tmp_path):
    cp = make_checkpoint(tmp_path)
    job = cp['jobs'][0]
    (tmp_path / 'restriction.json').rename(tmp_path / 'company-logo.json')
    job['receipt_paths'][1] = 'company-logo.json'
    job['receipt_sha256']['company-logo.json'] = job['receipt_sha256'].pop('restriction.json')
    validate_checkpoint(cp, base_dir=tmp_path)
    # An unrelated company file, even re-pinned, cannot stand in for a receipt.
    raw = b'{}'
    (tmp_path / 'company-logo.json').write_bytes(raw)
    job['receipt_sha256']['company-logo.json'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(GuardError, match='schema'):
        validate_checkpoint(cp, base_dir=tmp_path)


@pytest.mark.parametrize('field,value', [
    ('schema', 'unrelated-v1'), ('role', 'rights'), ('role', 'mpa'), ('role', []),
    ('job_id', 'other-job'), ('status', 'FAILED'), ('status', 'REFUSED'),
    ('status', 'PASS_WITH_HOLD'), ('holds', ['unresolved']), ('holds_added', ['unresolved']),
    ('holds', None),
])
def test_publication_receipt_fields_fail_closed(tmp_path, field, value):
    cp = make_checkpoint(tmp_path)
    doc = json.loads((tmp_path / 'restriction.json').read_bytes())
    doc[field] = value
    replace_doc(tmp_path, cp, doc)
    with pytest.raises(GuardError):
        validate_checkpoint(cp, base_dir=tmp_path)


@pytest.mark.parametrize('value', [None, [], 'not a receipt', {}])
def test_non_receipt_json_is_refused(tmp_path, value):
    cp = make_checkpoint(tmp_path)
    replace_doc(tmp_path, cp, value)
    with pytest.raises(GuardError):
        validate_checkpoint(cp, base_dir=tmp_path)


@pytest.mark.parametrize('mutation', ['missing-pin', 'wrong-pin', 'stale-pin', 'missing-file',
                                      'malformed', 'oversize', 'duplicate-path', 'alias', 'hardlink'])
def test_receipt_file_identity_and_pins(tmp_path, mutation):
    cp = make_checkpoint(tmp_path)
    job = cp['jobs'][0]
    path = tmp_path / 'restriction.json'
    if mutation == 'missing-pin':
        del job['receipt_sha256']
    elif mutation == 'wrong-pin':
        job['receipt_sha256']['restriction.json'] = '0' * 64
    elif mutation == 'stale-pin':
        path.write_bytes(path.read_bytes() + b' ')
    elif mutation == 'missing-file':
        path.unlink()
    elif mutation in ('malformed', 'oversize'):
        raw = b'{' if mutation == 'malformed' else b' ' * 65537
        path.write_bytes(raw)
        job['receipt_sha256']['restriction.json'] = hashlib.sha256(raw).hexdigest()
    elif mutation == 'duplicate-path':
        job['receipt_paths'][1] = 'rights.json'
        job['receipt_sha256'].pop('restriction.json')
    else:
        path.unlink()
        if mutation == 'alias':
            path.symlink_to(tmp_path / 'rights.json')
        else:
            os.link(tmp_path / 'rights.json', path)
        job['receipt_sha256']['restriction.json'] = job['receipt_sha256']['rights.json']
    with pytest.raises(GuardError):
        validate_checkpoint(cp, base_dir=tmp_path)
