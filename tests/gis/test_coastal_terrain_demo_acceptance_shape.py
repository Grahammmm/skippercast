import pytest
pytest.importorskip('numpy')
import hashlib
import json
from skippercast.coastal.render import terrain_demo as module

BAD = [[], [['k', 'v']], [{}], None, '', 'text', 0, 7, 1.5, True, False]
REASON = 'acceptance_context_or_holds_mismatch'


def receipt_bytes(**changes):
    document = dict(schema='coastal-terrain-only-render-v1', state='done', display_z='negative_depth_m_positive_up',
                    render_binding='a' * 64, acceptance_context_sha256='b' * 64, artifacts=[], **module.FLAGS)
    document.update(changes)
    return json.dumps(document).encode()


def write(tmp_path, data):
    (tmp_path / 'receipt.json').write_bytes(data)
    return dict(path='receipt.json', sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))


@pytest.mark.parametrize('value', BAD)
def test_nonobject_acceptance_refuses_before_context_use(tmp_path, value):
    descriptor = write(tmp_path, receipt_bytes(acceptance=value))
    with pytest.raises(ValueError, match=REASON):
        module.payload(tmp_path, descriptor)


@pytest.mark.parametrize('value', [[], None, 'x', 3, True])
def test_real_cli_returns_one_held_document_without_output(tmp_path, capsys, value):
    descriptor = write(tmp_path, receipt_bytes(acceptance=value))
    code = module.main(['--root', str(tmp_path), '--render-receipt', descriptor['path'], '--receipt-sha256', descriptor['sha256'],
                        '--receipt-bytes', str(descriptor['bytes']), '--output-dir', 'out'])
    out = capsys.readouterr().out
    assert code == 2
    result = json.loads(out)
    assert result['state'] == 'held' and result['holds'] == [REASON]
    assert not (tmp_path / 'out').exists()


def test_object_context_validation_is_not_relaxed(tmp_path):
    for acceptance in ({}, {'schema': 'wrong'}, {'schema': 'coastal-terrain-only-input-v1'},
                       dict(schema='coastal-terrain-only-input-v1', **module.FLAGS)):
        descriptor = write(tmp_path, receipt_bytes(acceptance=acceptance))
        with pytest.raises(ValueError, match=REASON):
            module.payload(tmp_path, descriptor)
    descriptor = write(tmp_path, receipt_bytes())
    with pytest.raises(KeyError):
        module.payload(tmp_path, descriptor)
    descriptor = write(tmp_path, receipt_bytes(acceptance=[], state='held'))
    with pytest.raises(ValueError, match='internal_render_receipt_required'):
        module.payload(tmp_path, descriptor)


def test_descriptor_authentication_still_precedes_shape(tmp_path):
    descriptor = write(tmp_path, receipt_bytes(acceptance=[]))
    with pytest.raises(ValueError, match='artifact_hash_or_bytes_changed'):
        module.payload(tmp_path, dict(descriptor, sha256='0' * 64))
    with pytest.raises(ValueError, match='artifact_bytes_changed'):
        module.payload(tmp_path, dict(descriptor, bytes=descriptor['bytes'] + 1))
