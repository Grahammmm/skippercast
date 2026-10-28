"""SC-PNG-DTYPE: write_png accepts only the fixed 480x640x3 uint8 RGB preview array.

docs/engineering/sc_png_dtype.md describes the contract. Every PNG written here is
decoded again by an independent stdlib reader (chunk lengths, binascii CRCs, IHDR,
zlib scanlines) and compared with RGB bytes computed in pure Python, never with a
second projection of the array under test. Incompatible dtypes (wider unsigned,
signed, float, complex, bool, bytes and object arrays of the right shape) must be
refused with ValueError before any byte is encoded or any target file is opened.

Synthetic, offline data only: network and process sentinels are installed before
the production module is imported, and every file lives under pytest's tmp_path.
"""
import ast
import binascii
import builtins
import fnmatch
import hashlib
import importlib
import json
import os
import pathlib
import socket
import struct
import subprocess
import sys
import tomllib
import types
import urllib.request
import http.client
import zlib
from pathlib import Path

import numpy as np
import pytest

from tests._support import ROOT as REPO

MODULE_NAME = 'skippercast.coastal.render.mesh'
MODULE_FILE = REPO / 'src' / 'skippercast' / 'coastal' / 'render' / 'mesh.py'
FIXTURE = REPO / 'tests' / 'fixtures' / 'sc_png_dtype' / 'baseline.json'
WIDTH, HEIGHT = 640, 480
REFUSAL = 'fixed_preview_uint8_required'
CONTRACT_MARKER = 'SC-PNG-DTYPE-CONTRACT'
NO_REFUSAL_MARKER = 'SC-PNG-DTYPE-NOT-REFUSED'
MESH_TOP_LEVEL_IMPORTS = {'math', 'struct', 'zlib', 'pathlib'}

INCOMPATIBLE_DTYPES = ['uint16', '>u2', 'uint32', 'uint64', 'int8', 'int16', 'int32', 'int64',
                       'float16', 'float32', 'float64', 'complex64', 'bool', 'S1', 'object']
WRONG_SHAPES = [(HEIGHT, WIDTH, 4), (HEIGHT, WIDTH, 1), (WIDTH, HEIGHT, 3), (HEIGHT - 1, WIDTH, 3),
                (HEIGHT, WIDTH), (HEIGHT, WIDTH, 3, 1)]


# --- offline sentinels and the complete production module ---------------------------------

def _refuse(name):
    def refused(*args, **kwargs):
        raise RuntimeError(f'offline sentinel: {name} is forbidden in SC-PNG-DTYPE tests')
    return refused


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Network/model/process sentinels; regression guards, not a hostile-code sandbox."""
    for owner, attr in ((socket, 'create_connection'), (socket, 'getaddrinfo'),
                        (socket.socket, 'connect'), (urllib.request, 'urlopen'),
                        (http.client.HTTPConnection, 'connect'), (subprocess, 'Popen'),
                        (os, 'system')):
        monkeypatch.setattr(owner, attr, _refuse(f'{getattr(owner, "__name__", owner)}.{attr}'))
    yield


@pytest.fixture
def mesh(offline):
    """Import the whole staged mesh module after the sentinels and an import inspection."""
    tree = ast.parse(MODULE_FILE.read_text(encoding='utf-8'))
    top = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            top.add((node.module or '').split('.')[0])
    assert top <= MESH_TOP_LEVEL_IMPORTS, f'mesh.py gained top-level imports {sorted(top)}'
    module = importlib.import_module(MODULE_NAME)
    assert Path(module.__file__).resolve() == MODULE_FILE.resolve(), module.__file__
    assert (module.WIDTH, module.HEIGHT) == (WIDTH, HEIGHT)
    return module


# --- synthetic pixels computed in pure Python -----------------------------------------------

def pattern_value(y, x, c):
    return (x * 7 + y * 13 + c * 101 + (x * y) % 17) % 256


def rgb_rows(value):
    return [bytes(value(y, x, c) for x in range(WIDTH) for c in range(3)) for y in range(HEIGHT)]


def scanlines(rows):
    return b''.join(b'\0' + row for row in rows)


def array_from_rows(rows, dtype='uint8'):
    flat = np.frombuffer(b''.join(rows), dtype=np.uint8).reshape(HEIGHT, WIDTH, 3)
    return flat.astype(dtype)


ZERO_ROWS = [bytes(WIDTH * 3)] * HEIGHT
PATTERN_ROWS = rgb_rows(pattern_value)
REVERSED_CHANNEL_ROWS = rgb_rows(lambda y, x, c: pattern_value(y, x, 2 - c))


# --- independent stdlib decoder of the fixed output format ----------------------------------

def contract_failure(reason):
    return AssertionError(f'{CONTRACT_MARKER}: {reason}')


def decode_fixed_png(data):
    """Return raw scanlines of an 8-bit RGB 640x480 PNG; AssertionError on any deviation."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise contract_failure('bad signature')
    offset, chunks = 8, []
    while offset < len(data):
        if offset + 12 > len(data):
            raise contract_failure('truncated chunk header')
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        if len(body) != length or offset + 12 + length > len(data):
            raise contract_failure(f'chunk {kind!r} length {length} overruns the file')
        crc = struct.unpack('>I', data[offset + 8 + length:offset + 12 + length])[0]
        if crc != binascii.crc32(kind + body) & 0xFFFFFFFF:
            raise contract_failure(f'chunk {kind!r} CRC mismatch')
        chunks.append((kind, body))
        offset += 12 + length
    if [kind for kind, _ in chunks] != [b'IHDR', b'IDAT', b'IEND']:
        raise contract_failure(f'chunk sequence {[kind for kind, _ in chunks]}')
    ihdr = chunks[0][1]
    if len(ihdr) != 13:
        raise contract_failure(f'IHDR length {len(ihdr)}')
    fields = struct.unpack('>IIBBBBB', ihdr)
    if fields != (WIDTH, HEIGHT, 8, 2, 0, 0, 0):
        raise contract_failure(f'IHDR fields {fields}')
    if chunks[2][1]:
        raise contract_failure('IEND carries data')
    inflater = zlib.decompressobj()
    raw = inflater.decompress(chunks[1][1]) + inflater.flush()
    if not inflater.eof or inflater.unused_data:
        raise contract_failure('IDAT is not one complete zlib stream')
    row_length = 1 + WIDTH * 3
    if len(raw) != HEIGHT * row_length:
        raise contract_failure(f'scanline bytes {len(raw)} != {HEIGHT} rows x {row_length}')
    for y in range(HEIGHT):
        if raw[y * row_length] != 0:
            raise contract_failure(f'row {y} filter byte {raw[y * row_length]}')
    return raw


def check_png_contract(data, rows):
    raw = decode_fixed_png(data)
    expected = scanlines(rows)
    if raw != expected:
        first = next(i for i, (a, b) in enumerate(zip(raw, expected)) if a != b)
        raise contract_failure(f'RGB bytes differ first at scanline offset {first}')
    return raw


def stdlib_reference_png(rows):
    """The documented fixed encoding, assembled from stdlib parts in this test."""
    def chunk(kind, body):
        return (struct.pack('>I', len(body)) + kind + body
                + struct.pack('>I', binascii.crc32(kind + body) & 0xFFFFFFFF))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', WIDTH, HEIGHT, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(scanlines(rows), 6)) + chunk(b'IEND', b''))


def legacy_write_png_without_dtype_guard(path, rgb):
    """Test-local double of the base (59fca09b) write_png: shape check only, no dtype guard."""
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    h, w, channels = rgb.shape
    if channels != 3 or w != WIDTH or h != HEIGHT:
        raise ValueError('fixed_preview_size_required')
    data = b''.join(b'\0' + row.tobytes() for row in rgb)
    encoded = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
               + chunk(b'IDAT', zlib.compress(data, 6)) + chunk(b'IEND', b''))
    Path(path).write_bytes(encoded)


def baseline():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def assert_matches_baseline(name, data, rows):
    frozen = baseline()['images'][name]
    raw = check_png_contract(data, rows)
    assert hashlib.sha256(raw).hexdigest() == frozen['raw_scanlines_sha256']
    assert data == stdlib_reference_png(rows), 'bytes differ from the fixed stdlib encoding'
    if zlib.ZLIB_RUNTIME_VERSION == baseline()['zlib_runtime_version']:
        assert len(data) == frozen['png_length']
        assert hashlib.sha256(data).hexdigest() == frozen['png_sha256']


# --- A1 positive contract -------------------------------------------------------------------

def test_a1_all_zero_matches_frozen_baseline(mesh, tmp_path):
    target = tmp_path / 'zero.png'
    mesh.write_png(target, np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8))
    assert_matches_baseline('all_zero', target.read_bytes(), ZERO_ROWS)


def test_a1_pattern_matches_frozen_baseline(mesh, tmp_path):
    target = tmp_path / 'pattern.png'
    mesh.write_png(target, array_from_rows(PATTERN_ROWS))
    assert_matches_baseline('pattern', target.read_bytes(), PATTERN_ROWS)


def test_a1_noncontiguous_column_view_keeps_logical_order(mesh, tmp_path):
    wide = np.full((HEIGHT, WIDTH * 2, 3), 255, dtype=np.uint8)
    wide[:, ::2] = array_from_rows(PATTERN_ROWS)
    view = wide[:, ::2]
    assert not view.flags.c_contiguous and view.base is not None
    target = tmp_path / 'strided.png'
    mesh.write_png(target, view)
    assert_matches_baseline('pattern', target.read_bytes(), PATTERN_ROWS)


def test_a1_reversed_channel_and_row_views_keep_logical_order(mesh, tmp_path):
    pixels = array_from_rows(PATTERN_ROWS)
    channels = tmp_path / 'channels.png'
    mesh.write_png(channels, pixels[..., ::-1])
    check_png_contract(channels.read_bytes(), REVERSED_CHANNEL_ROWS)
    flipped = tmp_path / 'flipped.png'
    mesh.write_png(flipped, pixels[::-1])
    check_png_contract(flipped.read_bytes(), PATTERN_ROWS[::-1])


def test_a1_fortran_order_and_readonly_arrays_keep_logical_order(mesh, tmp_path):
    fortran = np.asfortranarray(array_from_rows(PATTERN_ROWS))
    assert not fortran.flags.c_contiguous
    readonly = array_from_rows(PATTERN_ROWS)
    readonly.flags.writeable = False
    for name, pixels in (('fortran.png', fortran), ('readonly.png', readonly)):
        mesh.write_png(tmp_path / name, pixels)
        assert_matches_baseline('pattern', (tmp_path / name).read_bytes(), PATTERN_ROWS)


def test_a1_valid_array_still_replaces_an_existing_target(mesh, tmp_path):
    target = tmp_path / 'preview.png'
    target.write_bytes(b'older synthetic preview')
    mesh.write_png(str(target), np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8))
    assert_matches_baseline('all_zero', target.read_bytes(), ZERO_ROWS)


# --- A2 failure and preservation contract ---------------------------------------------------

class TobytesSpy(np.ndarray):
    calls = []

    def tobytes(self, *args, **kwargs):
        TobytesSpy.calls.append(self.shape)
        return np.ndarray.tobytes(self, *args, **kwargs)


def incompatible(dtype):
    if dtype == 'object':
        pixels = np.empty((HEIGHT, WIDTH, 3), dtype=object)
        pixels[...] = 0
        return pixels
    if dtype == 'bool':
        return np.zeros((HEIGHT, WIDTH, 3), dtype=bool)
    if dtype == 'S1':
        return np.full((HEIGHT, WIDTH, 3), b'\0', dtype='S1')
    # In-range values: refusal must not depend on whether narrowing would be lossless.
    return array_from_rows(PATTERN_ROWS, dtype)


def refuse_side_effects(mesh, monkeypatch, record):
    def opened(name):
        def refused(*args, **kwargs):
            record.append(name)
            raise RuntimeError(f'target touched through {name} before the dtype refusal')
        return refused
    monkeypatch.setattr(pathlib.Path, 'write_bytes', opened('Path.write_bytes'))
    monkeypatch.setattr(pathlib.Path, 'open', opened('Path.open'))
    monkeypatch.setattr(builtins, 'open', opened('open'))
    monkeypatch.setattr(os, 'open', opened('os.open'))
    monkeypatch.setattr(mesh, 'zlib', types.SimpleNamespace(compress=opened('zlib.compress'),
                                                           crc32=opened('zlib.crc32')))


@pytest.mark.parametrize('dtype', INCOMPATIBLE_DTYPES)
def test_a2_incompatible_dtype_refused_before_encoding_or_open(mesh, tmp_path, monkeypatch, dtype):
    pixels = incompatible(dtype).view(TobytesSpy)
    assert pixels.shape == (HEIGHT, WIDTH, 3) and pixels.dtype == np.dtype(dtype)
    target = tmp_path / 'preview.png'
    record = []
    TobytesSpy.calls = []
    with monkeypatch.context() as patched:
        refuse_side_effects(mesh, patched, record)
        with pytest.raises(ValueError) as refused:
            mesh.write_png(target, pixels)
    assert str(refused.value) == REFUSAL
    assert record == [] and TobytesSpy.calls == []
    assert not target.exists() and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('dtype', INCOMPATIBLE_DTYPES)
def test_a2_incompatible_dtype_keeps_existing_target_bytes(mesh, tmp_path, dtype):
    target = tmp_path / 'preview.png'
    original = b'SC-PNG-DTYPE existing synthetic target\n'
    target.write_bytes(original)
    before = target.stat()
    with pytest.raises(ValueError, match=f'^{REFUSAL}$'):
        mesh.write_png(target, incompatible(dtype))
    after = target.stat()
    assert target.read_bytes() == original
    assert (after.st_ino, after.st_size, after.st_mtime_ns) == (before.st_ino, before.st_size, before.st_mtime_ns)


def test_a2_uint16_refused_before_encoding(mesh, tmp_path):
    """Decisive regression: an in-range uint16 array is refused, never written as 16-bit samples."""
    target = tmp_path / 'preview.png'
    try:
        mesh.write_png(target, array_from_rows(PATTERN_ROWS, 'uint16'))
    except ValueError as error:
        assert str(error) == REFUSAL
        assert not target.exists()
        return
    # The guard was bypassed: the independent output contract must expose the bad encoding.
    check_png_contract(target.read_bytes(), PATTERN_ROWS)
    pytest.fail(f'{NO_REFUSAL_MARKER}: uint16 accepted and a contract-valid PNG written')


@pytest.mark.parametrize('shape', WRONG_SHAPES, ids=lambda shape: 'x'.join(map(str, shape)))
@pytest.mark.parametrize('dtype', ['uint8', 'uint16'])
def test_a2_wrong_shape_still_refused(mesh, tmp_path, shape, dtype):
    target = tmp_path / 'preview.png'
    with pytest.raises(ValueError):
        mesh.write_png(target, np.zeros(shape, dtype=dtype))
    assert not target.exists()


# --- A3 decisive negative control (test-local bypass; production source untouched) ---------

def test_a3_bypass_writes_invalid_uint16_scanlines(tmp_path):
    target = tmp_path / 'bypass.png'
    legacy_write_png_without_dtype_guard(target, array_from_rows(PATTERN_ROWS, 'uint16'))
    data = target.read_bytes()
    idat_length = struct.unpack('>I', data[33:37])[0]
    assert data[37:41] == b'IDAT'
    raw = zlib.decompress(data[41:41 + idat_length])
    assert len(raw) == HEIGHT * (1 + WIDTH * 3 * 2), 'bypass did not emit 16-bit sample bytes'
    with pytest.raises(AssertionError, match=f'^{CONTRACT_MARKER}: scanline bytes'):
        check_png_contract(data, PATTERN_ROWS)


def test_a3_bypass_and_production_agree_on_valid_uint8(mesh, tmp_path):
    pixels = array_from_rows(PATTERN_ROWS)
    legacy_write_png_without_dtype_guard(tmp_path / 'legacy.png', pixels)
    mesh.write_png(tmp_path / 'patched.png', pixels)
    legacy, patched = (tmp_path / 'legacy.png').read_bytes(), (tmp_path / 'patched.png').read_bytes()
    assert patched == legacy
    assert_matches_baseline('pattern', patched, PATTERN_ROWS)


def test_a3_contract_checker_detects_tampering():
    good = stdlib_reference_png(PATTERN_ROWS)
    check_png_contract(good, PATTERN_ROWS)
    bad_crc = good[:29] + bytes([good[29] ^ 1]) + good[30:]
    ihdr16 = struct.pack('>IIBBBBB', WIDTH, HEIGHT, 16, 2, 0, 0, 0)
    bad_depth = (good[:16] + ihdr16 + struct.pack('>I', binascii.crc32(b'IHDR' + ihdr16)) + good[33:])
    other_rows = list(PATTERN_ROWS)
    other_rows[7] = bytes(WIDTH * 3)
    for data, rows, reason in ((bad_crc, PATTERN_ROWS, 'CRC mismatch'),
                               (bad_depth, PATTERN_ROWS, 'IHDR fields'),
                               (good[:-5], PATTERN_ROWS, 'truncated'),
                               (good, other_rows, 'RGB bytes differ')):
        with pytest.raises(AssertionError, match=CONTRACT_MARKER) as failure:
            check_png_contract(data, rows)
        assert reason in str(failure.value)


# --- A4 module identity and discovery -------------------------------------------------------

def test_a4_tests_import_the_complete_staged_production_module(mesh):
    for name in ('camera_projection', 'build_mesh', 'render_png', 'write_png'):
        assert callable(getattr(mesh, name, None)), name
    assert mesh.write_png.__module__ == MODULE_NAME
    assert sys.modules[MODULE_NAME] is mesh


def test_a4_new_test_file_matches_configured_discovery(request):
    config = tomllib.loads((REPO / 'pyproject.toml').read_text(encoding='utf-8'))['tool']['pytest']['ini_options']
    relative = request.path.resolve().relative_to(REPO)
    assert relative.parts[0] in config['testpaths'] and relative.parts[1] == 'gis'
    assert any(fnmatch.fnmatch(relative.name, pattern) for pattern in config['python_files'])


def test_a4_offline_sentinels_are_installed():
    with pytest.raises(RuntimeError, match='offline sentinel'):
        socket.create_connection(('192.0.2.1', 9))
    with pytest.raises(RuntimeError, match='offline sentinel'):
        subprocess.Popen(['true'])
