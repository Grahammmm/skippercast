"""The R8 gate joins real file bytes, git history and independent stage/release pins, not filenames."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from types import SimpleNamespace
import zlib

import pytest

from scripts.relief import morro_release_packet_check as cli


ORIGIN = 'https://skippercast-morro-stage.example.workers.dev'
ENVELOPE = 'a' * 64
WIRE = 'b' * 64
PINS = {'wire': {'bytes': 100, 'sha256': WIRE}, 'decoded': {'bytes': 250, 'sha256': 'c' * 64}}
OLD_PINS = {'wire': {'bytes': 90, 'sha256': 'd' * 64}, 'decoded': {'bytes': 240, 'sha256': 'e' * 64}}
NEW_PINS = {'wire': {'bytes': 110, 'sha256': '1' * 64}, 'decoded': {'bytes': 260, 'sha256': '2' * 64}}
SIGNATURE = b'\x89PNG\r\n\x1a\n'


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _pointer(pins):
    return json.dumps({'schema': 'sc-relief-pointer/1', 'region': 'morro-bay', 'status': 'reviewed',
                       'private': False, 'envelope_sha256': ENVELOPE, 'survey_detail': pins}).encode()


@pytest.fixture(scope='module')
def history(tmp_path_factory):
    """A tiny real clone: the pointer changes at OLD, MERGE and NEWER; LATER touches something else.

    Real git, because the contract is git's own first-parent/blob answers. The checker only reads it."""
    repo = tmp_path_factory.mktemp('history')

    def git(*args):
        done = subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
                               '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', '-C', str(repo), *args],
                              capture_output=True, check=True, timeout=60)
        return done.stdout.decode().strip()

    def commit(name, content):
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        git('add', name)
        git('commit', '-q', '--no-verify', '-m', name)
        return git('rev-parse', 'HEAD')

    git('init', '-q')
    key = cli.POINTER_KEY
    old = commit(key, _pointer(OLD_PINS))
    merge = commit(key, _pointer(PINS))
    later = commit('notes.txt', b'unrelated\n')
    newer = commit(key, _pointer(NEW_PINS))
    return SimpleNamespace(repo=repo, old=old, merge=merge, later=later, newer=newer)


def _png(value, width=390, height=844):
    return _make_png([(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)),
                      (b'IDAT', zlib.compress((b'\0' + bytes([value]) * width) * height)), (b'IEND', b'')])


def _make_png(chunks):
    return SIGNATURE + b''.join(struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
                                for kind, data in chunks)


@pytest.fixture
def packet(tmp_path, history):
    """A passing packet whose pointer was merged at the deployed commit (deploy reason `equal`)."""
    pointer = _pointer(PINS)
    (tmp_path / 'pointer.json').write_bytes(pointer)
    commit = history.merge
    plan = {'schema': 'sc-morro-stage-preview/1', 'region': 'morro-bay', 'worker': 'skippercast-morro-stage',
            'commit': commit, 'pointer_sha256': _sha(pointer)}
    checks: list[dict[str, object]] = [{'check': key, 'status': 'PASS', 'reason': reason} for key, reason in
              [('deploy', 'equal'), ('pointer', 'identical'), ('contours', 'identical')]]
    checks.append({'check': 'survey', 'status': 'PASS', 'reason': 'identical', **PINS,
                   'key': f'feeds/tiles/relief/morro-bay/{ENVELOPE}/survey/{WIRE}.geojson.br'})
    live = {'region': 'morro-bay', 'base': ORIGIN, 'merge': history.merge, 'deployed': commit, 'verdict': 'PASS',
            'checks': checks}
    capture = {'schema': 'sc-morro-stage-phone/1', 'shots': []}
    for n, (theme, zoom) in enumerate((t, z) for t in ('light', 'dark') for z in (11, 13, 15)):
        data = _png(n)
        (tmp_path / f'{theme}-phone-z{zoom}.png').write_bytes(data)
        capture['shots'].append(dict(theme=theme, zoom=zoom, url=f'{ORIGIN}/#chart', region='morro-bay',
                                     commit=commit, pointer_sha256=_sha(pointer), envelope_sha256=ENVELOPE,
                                     layers_closed=True, viewport=[390, 844], png_sha256=_sha(data)))
    return SimpleNamespace(root=tmp_path, docs={'stage-plan': plan, 'live': live, 'capture': capture}, history=history)


def _run(packet, origin=ORIGIN, repo=None):
    args = ['--stage-origin', origin, '--envelope-sha256', ENVELOPE, '--repo', str(repo or packet.history.repo),
            '--pointer', str(packet.root / 'pointer.json')]
    for key, doc in packet.docs.items():
        path = packet.root / f'{key}.json'
        path.write_text(json.dumps(doc), encoding='utf-8')
        args.extend([f'--{key}', str(path)])
    return cli.main(args)


def test_six_hosted_views_link_to_one_release(packet, capsys):
    assert _run(packet) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['envelope_sha256'] == ENVELOPE and report['commit'] == packet.history.merge
    assert {(row['theme'], row['zoom']) for row in report['shots']} == {
        (theme, zoom) for theme in ('dark', 'light') for zoom in (11, 13, 15)}


# A stale shot or a loopback/production snapshot must not ride on five good ones.
@pytest.mark.parametrize(('field', 'value'), [
    ('url', 'http://127.0.0.1:8000/#chart'), ('url', 'https://skippercast.com/#chart'),
    ('url', f'{ORIGIN}.example.org/#chart'), ('envelope_sha256', 'd' * 64), ('commit', '5' * 40),
    ('pointer_sha256', '1' * 64), ('region', 'big-sur'), ('layers_closed', False),
    ('viewport', [1280, 800]), ('zoom', 11.0), ('theme', 'system'),
])
def test_one_mislabeled_view_refuses_packet(packet, field, value):
    packet.docs['capture']['shots'][0][field] = value
    assert _run(packet) == 1


def test_six_rows_with_a_duplicate_are_not_the_full_matrix(packet):
    shots = packet.docs['capture']['shots']
    shots[-1] = shots[0]
    assert _run(packet) == 1
    shots.pop()
    assert _run(packet) == 1


@pytest.mark.parametrize('case', ['bytes-replaced', 'same-image-twice', 'wrong-viewport'])
def test_verify_png_bytes_not_just_row_metadata(packet, case):
    row = packet.docs['capture']['shots'][0]
    data = (packet.root / 'dark-phone-z11.png').read_bytes() if case != 'wrong-viewport' else _png(0, 450, 600)
    (packet.root / 'light-phone-z11.png').write_bytes(data)
    if case != 'bytes-replaced':
        row['png_sha256'] = _sha(data)
    assert _run(packet) == 1


def _retarget(packet, commit):
    """Deploy `commit` instead: the plan, the receipt and every shot name it."""
    packet.docs['stage-plan']['commit'] = packet.docs['live']['deployed'] = commit
    for row in packet.docs['capture']['shots']:
        row['commit'] = commit


def _ancestor(packet):
    """The pointer merged earlier (MERGE) and a later commit (LATER) is what the stage serves."""
    _retarget(packet, packet.history.later)
    packet.docs['live']['checks'][0]['reason'] = 'ancestor'


def test_pointer_merged_before_the_deployed_commit_is_bound_by_git(packet):
    _ancestor(packet)
    assert _run(packet) == 0


def _historical_pointer(packet):
    """A genuine ancestor receipt for the OLD pointer: receipt, pointer file, plan and survey all agree."""
    _ancestor(packet)
    raw = _pointer(OLD_PINS)
    (packet.root / 'pointer.json').write_bytes(raw)
    packet.docs['stage-plan']['pointer_sha256'] = _sha(raw)
    packet.docs['live']['merge'] = packet.history.old
    survey = packet.docs['live']['checks'][3]
    survey.update(OLD_PINS, key=f'feeds/tiles/relief/morro-bay/{ENVELOPE}/survey/{OLD_PINS["wire"]["sha256"]}.geojson.br')
    for row in packet.docs['capture']['shots']:
        row['pointer_sha256'] = _sha(raw)


# Contract: the receipt and pointer must be proved against this planned commit by git, not by a flag or
# by agreeing with each other. Bug caught: a genuine ancestor PASS for an older pointer certified a candidate.
@pytest.mark.parametrize('case', ['other-receipt-merge', 'old-pointer-with-matching-old-receipt',
                                  'pointer-changed-after-merge', 'equal-with-earlier-merge',
                                  'ancestor-with-same-merge', 'receipt-without-merge', 'commit-not-in-clone'])
def test_pointer_and_receipt_are_bound_to_the_planned_commit_by_git(packet, case):
    history = packet.history
    if case == 'old-pointer-with-matching-old-receipt':
        _historical_pointer(packet)
    elif case == 'other-receipt-merge':
        _ancestor(packet)
        packet.docs['live']['merge'] = history.old
    elif case == 'pointer-changed-after-merge':
        _retarget(packet, history.newer)  # NEWER carries a different pointer than the supplied bytes
        packet.docs['live']['checks'][0]['reason'] = 'ancestor'
    elif case == 'equal-with-earlier-merge':
        _ancestor(packet)
        packet.docs['live']['checks'][0]['reason'] = 'equal'
    elif case == 'ancestor-with-same-merge':
        packet.docs['live']['checks'][0]['reason'] = 'ancestor'
    elif case == 'receipt-without-merge':
        _ancestor(packet)
        del packet.docs['live']['merge']
    else:
        _retarget(packet, '7' * 40)
    assert _run(packet) == 1


def test_old_pointer_packet_is_only_refused_for_its_git_binding(packet, history):
    # Same genuine historical packet, but planned at the commit that really merged it: it passes.
    _historical_pointer(packet)
    _retarget(packet, history.old)
    packet.docs['live']['checks'][0]['reason'] = 'equal'
    assert _run(packet) == 0


def test_repo_must_be_the_clone_root(packet, history):
    assert _run(packet, repo=history.repo / 'catalog') == 1


def _chunks(png):
    pos, out = len(SIGNATURE), []
    while pos < len(png):
        size = struct.unpack('>I', png[pos:pos + 4])[0]
        out.append((png[pos + 4:pos + 8], png[pos + 8:pos + 8 + size]))
        pos += 12 + size
    return out


def _bad_crc(png):
    return png[:41] + bytes([png[41] ^ 1]) + png[42:]  # first IDAT data byte


# Contract: the six-view packet only accepts screenshots that decode as a whole image.
# Bug caught: prefix/size/suffix-only check passed a PNG with junk chunks and no image data.
@pytest.mark.parametrize('case', ['no-image-data', 'junk-between-header-and-end', 'bad-crc', 'bad-zlib',
                                  'short-pixels', 'extra-pixels', 'trailing-bytes', 'truncated', 'invalid-filter-byte'])
def test_png_must_be_a_decodable_image_not_just_a_matching_frame(packet, case):
    good = (packet.root / 'light-phone-z11.png').read_bytes()
    head, _, end = _chunks(good)
    if case == 'no-image-data':
        data = _make_png([head, end])
    elif case == 'junk-between-header-and-end':
        data = _make_png([head, (b'abcd', b'junk'), end])
    elif case == 'bad-crc':
        data = _bad_crc(good)
    elif case == 'bad-zlib':
        data = _make_png([head, (b'IDAT', b'not zlib'), end])
    elif case == 'short-pixels':
        data = _make_png([head, (b'IDAT', zlib.compress(b'\0' * 390)), end])
    elif case == 'extra-pixels':
        data = _make_png([head, (b'IDAT', zlib.compress(b'\0' * (391 * 845))), end])
    elif case == 'trailing-bytes':
        data = good + b'x'
    elif case == 'invalid-filter-byte':  # the right size and a clean CRC, but filter type 255 on every row
        data = _make_png([head, (b'IDAT', zlib.compress((b'\xff' + b'\0' * 390) * 844)), end])
    else:
        data = good[:-20]
    (packet.root / 'light-phone-z11.png').write_bytes(data)
    packet.docs['capture']['shots'][0]['png_sha256'] = _sha(data)
    assert _run(packet) == 1


def _header(width, height, depth=8, color=0, interlace=0):
    return b'IHDR', struct.pack('>IIBBBBB', width, height, depth, color, 0, 0, interlace)


def _scanlines(sizes, bits, filters=(0,), fill=b'\x00'):
    """Raw image data: one filter byte then `fill` bytes per row, cycling through `filters`."""
    rows, out = 0, b''
    for columns, count in sizes:
        for _ in range(count):
            out += bytes([filters[rows % len(filters)]]) + fill * -(-columns * bits // 8)
            rows += 1
    return out


def _image(head, data, before=(), after=(), split=False):
    pixels = [(b'IDAT', zlib.compress(data))]
    if split:
        pixels = [(b'IDAT', pixels[0][1][:3]), (b'IDAT', pixels[0][1][3:])]
    return _make_png([head, *before, *pixels, *after, (b'IEND', b'')])


ADAM7_5X5 = [(1, 1), (1, 1), (2, 1), (1, 2), (3, 1), (2, 3), (5, 2)]  # (columns, rows) per pass, by hand
PALETTE3 = (b'PLTE', bytes(range(9)))

# Contract: every PNG shape a phone browser can save is accepted once it is fully valid.
# Bug caught: a stricter decoder rejecting real screenshots would block a good packet.
VALID = {
    'grey8-all-filters': lambda: _image(_header(3, 5), _scanlines([(3, 5)], 8, (0, 1, 2, 3, 4))),
    'rgb8-sub-filter': lambda: _image(_header(4, 2, 8, 2), _scanlines([(4, 2)], 24, (1,), b'\x07')),
    'rgba16': lambda: _image(_header(2, 2, 16, 6), _scanlines([(2, 2)], 64, (4,))),
    'grey1-odd-width': lambda: _image(_header(9, 3, 1, 0), _scanlines([(9, 3)], 1)),
    'palette4-full': lambda: _image(_header(5, 2, 4, 3), _scanlines([(5, 2)], 4), [(b'PLTE', bytes(3 * 16))]),
    'palette2-in-range': lambda: _image(_header(4, 2, 2, 3), _scanlines([(4, 2)], 2, fill=b'\x55'), [PALETTE3]),
    'rgb-with-suggested-palette': lambda: _image(_header(2, 2, 8, 2), _scanlines([(2, 2)], 24), [PALETTE3]),
    # PNG 11.3.5.6: a histogram may describe a suggested palette in a truecolor image.
    'rgb-with-suggested-palette-histogram': lambda: _image(
        _header(2, 2, 8, 2), _scanlines([(2, 2)], 24), [PALETTE3, (b'hIST', b'\0' * 6)]),
    'rgba-with-two-entry-palette-histogram': lambda: _image(
        _header(2, 2, 8, 6), _scanlines([(2, 2)], 32), [(b'PLTE', bytes(6)), (b'hIST', b'\0\1\0\2')]),
    'palette-with-histogram': lambda: _image(
        _header(2, 2, 2, 3), _scanlines([(2, 2)], 2), [PALETTE3, (b'hIST', b'\0' * 6)]),
    'adam7-rgb': lambda: _image(_header(5, 5, 8, 2, 1), _scanlines(ADAM7_5X5, 24, (0, 1, 2, 3, 4))),
    'adam7-narrow': lambda: _image(_header(1, 1, 8, 0, 1), _scanlines([(1, 1)], 8)),
    'ancillary-and-split-idat': lambda: _image(
        _header(2, 2), _scanlines([(2, 2)], 8), [(b'gAMA', b'\0' * 4), (b'pHYs', b'\0' * 9), (b'tEXt', b'k\0v')],
        [(b'tIME', b'\0' * 7), (b'zzZz', b'')], split=True),
    'palette-transparency-and-background': lambda: _image(
        _header(2, 2, 2, 3), _scanlines([(2, 2)], 2), [PALETTE3, (b'tRNS', b'\xff\x80'), (b'bKGD', b'\x01')]),
}


@pytest.mark.parametrize('name', sorted(VALID))
def test_valid_pngs_of_every_colour_type_and_interlace_are_accepted(name):
    png = VALID[name]()
    assert cli._png_size(png) == struct.unpack('>II', _chunks(png)[0][1][:8])


# Contract: _png_size refuses anything a conforming decoder would refuse, in every interlace pass.
# Bug caught: sizes/CRC/zlib alone accepted bad scanline filters, palettes and chunk order.
def _bad_filter_in_last_pass():
    data = bytearray(_scanlines(ADAM7_5X5, 24))
    data[-(1 + 15)] = 5  # the filter byte of the final row of pass 7
    return _image(_header(5, 5, 8, 2, 1), bytes(data))


def _up_filter_leaves_palette():
    # Row 1 is index 1 everywhere; row 2 adds 0xAA with the Up filter -> index 3, outside a 3-entry palette.
    return _image(_header(4, 2, 2, 3), b'\x00\x55' + b'\x02\xaa', [PALETTE3])


BAD = {
    'filter-5': lambda: _image(_header(2, 2), b'\x05\0\0' + b'\0\0\0'),
    'filter-255-every-row': lambda: _image(_header(390, 844), _scanlines([(390, 844)], 8, (255,))),
    'filter-5-in-final-adam7-pass': _bad_filter_in_last_pass,
    'palette-index-out-of-range': lambda: _image(_header(4, 1, 2, 3), b'\x00\xff', [PALETTE3]),
    'up-filter-reaches-out-of-range-index': _up_filter_leaves_palette,
    'indexed-without-palette': lambda: _image(_header(2, 2, 8, 3), _scanlines([(2, 2)], 8)),
    'palette-on-greyscale': lambda: _image(_header(2, 2), _scanlines([(2, 2)], 8), [PALETTE3]),
    'palette-not-multiple-of-3': lambda: _image(_header(2, 2, 8, 2), _scanlines([(2, 2)], 24), [(b'PLTE', b'\0' * 4)]),
    'palette-bigger-than-depth': lambda: _image(_header(2, 2, 2, 3), _scanlines([(2, 2)], 2), [(b'PLTE', b'\0' * 15)]),
    'palette-after-image-data': lambda: _make_png([_header(2, 2, 8, 2), (b'IDAT', zlib.compress(_scanlines([(2, 2)], 24))),
                                                   PALETTE3, (b'IEND', b'')]),
    'two-palettes': lambda: _image(_header(2, 2, 8, 2), _scanlines([(2, 2)], 24), [PALETTE3, PALETTE3]),
    'palette-after-background': lambda: _image(_header(2, 2, 8, 2), _scanlines([(2, 2)], 24),
                                               [(b'bKGD', b'\0' * 6), PALETTE3]),
    'histogram-shorter-than-truecolor-palette': lambda: _image(
        _header(2, 2, 8, 2), _scanlines([(2, 2)], 24), [PALETTE3, (b'hIST', b'\0' * 4)]),
    'histogram-longer-than-palette': lambda: _image(
        _header(2, 2, 2, 3), _scanlines([(2, 2)], 2), [PALETTE3, (b'hIST', b'\0' * 8)]),
    'histogram-without-palette': lambda: _image(
        _header(2, 2, 8, 2), _scanlines([(2, 2)], 24), [(b'hIST', b'\0' * 6)]),
    'histogram-before-palette': lambda: _image(
        _header(2, 2, 8, 2), _scanlines([(2, 2)], 24), [(b'hIST', b'\0' * 6), PALETTE3]),
    'transparency-on-rgba': lambda: _image(_header(2, 2, 8, 6), _scanlines([(2, 2)], 32), [(b'tRNS', b'\0' * 6)]),
    'transparency-longer-than-palette': lambda: _image(_header(2, 2, 2, 3), _scanlines([(2, 2)], 2),
                                                       [PALETTE3, (b'tRNS', b'\xff' * 4)]),
    'background-outside-palette': lambda: _image(_header(2, 2, 2, 3), _scanlines([(2, 2)], 2),
                                                 [PALETTE3, (b'bKGD', b'\x03')]),
    'unknown-critical-chunk': lambda: _image(_header(2, 2), _scanlines([(2, 2)], 8), [(b'ABCD', b'')]),
    'reserved-bit-lower-case': lambda: _image(_header(2, 2), _scanlines([(2, 2)], 8), [(b'abcd', b'')]),
    'duplicate-header': lambda: _image(_header(2, 2), _scanlines([(2, 2)], 8), [_header(2, 2)]),
    'ancillary-before-header': lambda: _make_png([(b'tEXt', b'k\0v'), _header(2, 2),
                                                  (b'IDAT', zlib.compress(_scanlines([(2, 2)], 8))), (b'IEND', b'')]),
    'gamma-wrong-length': lambda: _image(_header(2, 2), _scanlines([(2, 2)], 8), [(b'gAMA', b'\0' * 3)]),
    'physical-size-after-image-data': lambda: _image(_header(2, 2), _scanlines([(2, 2)], 8), after=[(b'pHYs', b'\0' * 9)]),
    'duplicate-time': lambda: _image(_header(2, 2), _scanlines([(2, 2)], 8), after=[(b'tIME', b'\0' * 7)] * 2),
    'image-data-split-by-a-chunk': lambda: _make_png([
        _header(2, 2), (b'IDAT', zlib.compress(_scanlines([(2, 2)], 8))[:3]), (b'tEXt', b'k\0v'),
        (b'IDAT', zlib.compress(_scanlines([(2, 2)], 8))[3:]), (b'IEND', b'')]),
    'bad-bit-depth': lambda: _image(_header(2, 2, 3, 0), _scanlines([(2, 2)], 8)),
    'unsupported-interlace': lambda: _image(_header(2, 2, 8, 0, 2), _scanlines([(2, 2)], 8)),
    'end-with-data': lambda: _make_png([_header(2, 2), (b'IDAT', zlib.compress(_scanlines([(2, 2)], 8))), (b'IEND', b'x')]),
}


@pytest.mark.parametrize('name', sorted(BAD))
def test_malformed_pngs_are_refused(name):
    with pytest.raises(ValueError):
        cli._png_size(BAD[name]())


def test_every_valid_png_fixture_differs_from_its_broken_twin_only_by_the_defect():
    # Guard against the BAD table passing for the wrong reason: its base image is accepted.
    assert cli._png_size(_image(_header(2, 2), _scanlines([(2, 2)], 8))) == (2, 2)
    assert cli._png_size(_image(_header(4, 2, 2, 3), b'\x00\x55' + b'\x02\x00', [PALETTE3])) == (4, 2)


@pytest.mark.parametrize('case', ['wrong-stage', 'wrong-plan-worker', 'wrong-pointer', 'legacy-live',
                                  'wrong-survey', 'missing-contours', 'descendant-deploy', 'non-stage-worker'])
def test_capture_cannot_replace_independent_stage_and_candidate_proof(packet, case):
    docs = packet.docs
    live = docs['live']
    origin = ORIGIN
    if case == 'wrong-stage':
        live['base'] = 'https://another-stage.example.workers.dev'
    elif case == 'wrong-plan-worker':
        docs['stage-plan']['worker'] = 'another-stage'
    elif case == 'wrong-pointer':
        with (packet.root / 'pointer.json').open('ab') as stream:
            stream.write(b'\n')
    elif case == 'legacy-live':
        live['checks'].pop()
    elif case == 'wrong-survey':
        live['checks'][-1]['key'] = live['checks'][-1]['key'].replace(ENVELOPE, 'd' * 64)
    elif case == 'missing-contours':
        live['checks'][2]['reason'] = 'none-merged'
    elif case == 'descendant-deploy':
        live['deployed'] = '0' * 40
        live['checks'][0]['reason'] = 'ancestor'
    else:
        origin = live['base'] = 'https://skippercast.example.workers.dev'
        docs['stage-plan']['worker'] = 'skippercast'
        for row in docs['capture']['shots']:
            row['url'] = f'{origin}/#chart'
    assert _run(packet, origin) == 1
