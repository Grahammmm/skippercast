"""derived_batch.arrays decodes the one authenticated byte snapshot whose headers it inspected (RF2150-8).

Synthetic NPZ files only; real ref/hash/ZipFile header/NumPy paths with deterministic file mutation hooks.
"""
import io
import os
import zipfile

import numpy as np
import pytest

from skippercast.coastal import derived_batch
from skippercast.coastal.handoff.common import ref

CONTRACT = 'coastal-authenticated-arrays-v1'


def fields(side=128, depth=30.0):
    raw = np.arange(side * side, dtype='float32').reshape(side, side)
    mask = np.zeros((side, side), bool)
    mask[::3] = True
    return {'depth': np.full((side, side), depth, 'float64'), 'raw_elevation_data': raw,
            'raw_uncertainty_data': raw / 7, 'elevation_mask': mask, 'uncertainty_mask': ~mask,
            'source_pair_valid': mask.T.copy(), 'legacy_25_300ft_uncertainty_0_1m': mask & ~mask.T}


def npz_bytes(values):
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **values)
    return buffer.getvalue()


def members_bytes(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return buffer.getvalue()


def npy(value):
    buffer = io.BytesIO()
    np.save(buffer, value, allow_pickle=True)
    return buffer.getvalue()


def admit(tmp_path, payload):
    path = tmp_path / 'arrays.npz'
    path.write_bytes(payload)
    return path, ref(tmp_path, path, CONTRACT, cap=4 * 1024 * 1024)


@pytest.fixture
def after_headers(monkeypatch):
    """Run ``action`` once immediately after the real archive closes, whatever ZipFile was given."""
    real_exit, fired = zipfile.ZipFile.__exit__, []

    def install(action):
        def exit_then_mutate(self, *exc):
            result = real_exit(self, *exc)
            if not fired:
                fired.append(True)
                action()
            return result
        monkeypatch.setattr(zipfile.ZipFile, '__exit__', exit_then_mutate)
        return fired
    return install


@pytest.mark.parametrize('side, depth', [(129, 99.0), (128, 77.0)])
def test_replacement_after_headers_never_changes_shape_or_values(tmp_path, after_headers, side, depth):
    path, artifact = admit(tmp_path, npz_bytes(fields()))
    control = derived_batch.arrays(tmp_path, artifact)
    assert control['depth'].shape == (128, 128) and float(control['depth'][0, 0]) == 30.0
    replacement = npz_bytes(fields(side, depth))
    fired = after_headers(lambda: path.write_bytes(replacement))
    result = derived_batch.arrays(tmp_path, artifact)
    assert fired and path.read_bytes() == replacement  # the mutation really happened on disk
    for key, value in control.items():
        assert result[key].shape == (128, 128) and np.array_equal(result[key], value)
    assert float(result['depth'][0, 0]) == 30.0


@pytest.mark.parametrize('mutate', ['move', 'unrelated'])
def test_snapshot_survives_path_removal_or_replacement(tmp_path, after_headers, mutate):
    path, artifact = admit(tmp_path, npz_bytes(fields()))
    moved = tmp_path / 'moved.npz'
    action = (lambda: os.replace(path, moved)) if mutate == 'move' else (lambda: path.write_bytes(b'unrelated'))
    fired = after_headers(action)
    result = derived_batch.arrays(tmp_path, artifact)
    assert fired and (moved.exists() if mutate == 'move' else path.read_bytes() == b'unrelated')
    assert float(result['depth'][5, 5]) == 30.0 and result['raw_elevation_data'].shape == (128, 128)


def track_decoders(monkeypatch):
    calls = []
    real_zip, real_load = zipfile.ZipFile, np.load
    monkeypatch.setattr(zipfile, 'ZipFile', lambda *a, **k: calls.append('zip') or real_zip(*a, **k))
    monkeypatch.setattr(np, 'load', lambda *a, **k: calls.append('load') or real_load(*a, **k))
    return calls


def track_descriptors(monkeypatch):
    opened, closed = [], []
    real_open, real_close = os.open, os.close
    monkeypatch.setattr(os, 'open', lambda *a, **k: opened.append(real_open(*a, **k)) or opened[-1])
    monkeypatch.setattr(os, 'close', lambda fd: closed.append(fd) or real_close(fd))
    return opened, closed


@pytest.mark.parametrize('replacement', ['same_size', 'other'])
def test_replacement_between_resolve_and_capture_is_reauthenticated(tmp_path, monkeypatch, replacement):
    original = npz_bytes(fields())
    path, artifact = admit(tmp_path, original)
    swap = bytes(len(original)) if replacement == 'same_size' else npz_bytes(fields(depth=77.0))
    real_resolve = derived_batch.resolve

    def resolve_then_swap(*args, **kwargs):
        resolved = real_resolve(*args, **kwargs)
        path.write_bytes(swap)
        return resolved
    monkeypatch.setattr(derived_batch, 'resolve', resolve_then_swap)
    calls = track_decoders(monkeypatch)
    opened, closed = track_descriptors(monkeypatch)
    with pytest.raises(ValueError, match='snapshot'):
        derived_batch.arrays(tmp_path, artifact)
    assert path.read_bytes() == swap and calls == [] and opened and opened == closed
    assert artifact['bytes'] == len(original)


@pytest.mark.parametrize('cap, grow', [(64, 100), (4096, 10)])
def test_concurrent_growth_checks_actual_captured_bytes(tmp_path, monkeypatch, cap, grow):
    path, artifact = admit(tmp_path, b'x' * 40)
    monkeypatch.setattr(derived_batch, 'ARRAY_CAP', cap)
    real_fstat = os.fstat

    def fstat_then_grow(fd):
        info = real_fstat(fd)
        with path.open('ab') as stream:
            stream.write(b'y' * grow)
        return info
    monkeypatch.setattr(os, 'fstat', fstat_then_grow)
    calls = track_decoders(monkeypatch)
    opened, closed = track_descriptors(monkeypatch)
    with pytest.raises(ValueError, match='snapshot'):
        derived_batch.arrays(tmp_path, artifact)
    assert path.stat().st_size == 40 + grow and calls == [] and opened and opened == closed


def test_valid_snapshot_keeps_exact_worker_arrays(tmp_path, monkeypatch):
    values = fields()
    payload = npz_bytes(values)
    path, artifact = admit(tmp_path, payload)
    opened, closed = track_descriptors(monkeypatch)
    result = derived_batch.arrays(tmp_path, artifact)
    assert opened and opened == closed and path.read_bytes() == payload
    assert set(result) == set(values)
    for key, value in values.items():
        assert result[key].dtype == value.dtype and np.array_equal(result[key], value)
        assert result[key].flags.owndata and result[key].flags.writeable
    result['depth'][0, 0] = -1.0
    assert float(derived_batch.arrays(tmp_path, artifact)['depth'][0, 0]) == 30.0
    small = admit(tmp_path, npz_bytes(fields(side=4)))[1]
    assert derived_batch.arrays(tmp_path, small, side=4)['depth'].shape == (4, 4)
    with pytest.raises(ValueError, match='exact128x128'):
        derived_batch.arrays(tmp_path, small)


def edited(**changes):
    values = fields()
    values.update(changes)
    return [(key + '.npy', npy(value)) for key, value in values.items() if value is not None]


@pytest.mark.parametrize('members, message', [
    (edited() + [('extra.npy', npy(np.zeros((128, 128))))], 'members'),
    (edited(depth=None), 'members'),
    (edited() + [('depth.npy', npy(np.zeros((128, 128))))], 'members'),
    (edited(depth=np.zeros((128, 128), object)), 'exact128x128'),
    (edited(depth=np.zeros((128, 128), 'f8,f8')), 'exact128x128'),
    (edited(depth=np.zeros((129, 129))), 'exact128x128'),
    (edited(depth=np.zeros((128, 128), 'float32')), 'worker array dtypes'),
    (edited(depth=np.asfortranarray(np.zeros((128, 128)))), 'exact128x128'),
    (edited(depth=np.zeros((725, 725))), 'members'),
    ([(name, payload[:-8]) if name == 'depth.npy' else (name, payload) for name, payload in edited()], 'exact128x128'),
])
@pytest.mark.filterwarnings('ignore:Duplicate name')
def test_unchanged_archive_declaration_fences(tmp_path, monkeypatch, members, message):
    artifact = admit(tmp_path, members_bytes(members))[1]
    calls = track_decoders(monkeypatch)
    with pytest.raises(ValueError, match=message):
        derived_batch.arrays(tmp_path, artifact)
    if message != 'worker array dtypes':
        assert 'load' not in calls


@pytest.mark.parametrize('change', [{'sha256': '0' * 64}, {'bytes': 1}, {'contract': 'other'},
                                    {'path': 'arrays.bag'}, {'bytes': 4 * 1024 * 1024 + 1}])
def test_bad_descriptor_still_refuses(tmp_path, change):
    path, artifact = admit(tmp_path, npz_bytes(fields()))
    (tmp_path / 'arrays.bag').write_bytes(path.read_bytes())
    with pytest.raises(ValueError):
        derived_batch.arrays(tmp_path, {**artifact, **change})
