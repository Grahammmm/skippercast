"""The R8 gate joins real file bytes and independent stage/release pins, not filenames."""
import hashlib
import json
import struct
import zlib

import pytest

from scripts.relief import morro_release_packet_check as cli


ORIGIN = 'https://skippercast-morro-stage.example.workers.dev'
COMMIT = '9' * 40
MERGE = '4' * 40  # the earlier commit that merged the reviewed pointer
ENVELOPE = 'a' * 64
WIRE = 'b' * 64
PINS = {'wire': {'bytes': 100, 'sha256': WIRE}, 'decoded': {'bytes': 250, 'sha256': 'c' * 64}}


def _png(value, width=390, height=844):
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data))

    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + bytes([value]) * width) * height)) + chunk(b'IEND', b''))


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def packet(tmp_path):
    pointer = json.dumps({'schema': 'sc-relief-pointer/1', 'region': 'morro-bay', 'status': 'reviewed',
                          'private': False, 'envelope_sha256': ENVELOPE, 'survey_detail': PINS}).encode()
    (tmp_path / 'pointer.json').write_bytes(pointer)
    plan = {'schema': 'sc-morro-stage-preview/1', 'region': 'morro-bay', 'worker': 'skippercast-morro-stage',
            'commit': COMMIT, 'pointer_sha256': _sha(pointer)}
    checks: list[dict[str, object]] = [{'check': key, 'status': 'PASS', 'reason': reason} for key, reason in
              [('deploy', 'equal'), ('pointer', 'identical'), ('contours', 'identical')]]
    checks.append({'check': 'survey', 'status': 'PASS', 'reason': 'identical', **PINS,
                   'key': f'feeds/tiles/relief/morro-bay/{ENVELOPE}/survey/{WIRE}.geojson.br'})
    live = {'region': 'morro-bay', 'base': ORIGIN, 'merge': COMMIT, 'deployed': COMMIT, 'verdict': 'PASS',
            'checks': checks}
    capture = {'schema': 'sc-morro-stage-phone/1', 'shots': []}
    for n, (theme, zoom) in enumerate((t, z) for t in ('light', 'dark') for z in (11, 13, 15)):
        data = _png(n)
        (tmp_path / f'{theme}-phone-z{zoom}.png').write_bytes(data)
        capture['shots'].append(dict(theme=theme, zoom=zoom, url=f'{ORIGIN}/#chart', region='morro-bay',
                                     commit=COMMIT, pointer_sha256=_sha(pointer), envelope_sha256=ENVELOPE,
                                     layers_closed=True, viewport=[390, 844], png_sha256=_sha(data)))
    return tmp_path, {'stage-plan': plan, 'live': live, 'capture': capture}


def _run(packet, origin=ORIGIN, merge=COMMIT):
    root, docs = packet
    args = ['--stage-origin', origin, '--envelope-sha256', ENVELOPE, '--pointer-merge', merge,
            '--pointer', str(root / 'pointer.json')]
    for key, doc in docs.items():
        path = root / f'{key}.json'
        path.write_text(json.dumps(doc), encoding='utf-8')
        args.extend([f'--{key}', str(path)])
    return cli.main(args)


def test_six_hosted_views_link_to_one_release(packet, capsys):
    assert _run(packet) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['envelope_sha256'] == ENVELOPE and report['commit'] == COMMIT
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
    packet[1]['capture']['shots'][0][field] = value
    assert _run(packet) == 1


def test_six_rows_with_a_duplicate_are_not_the_full_matrix(packet):
    shots = packet[1]['capture']['shots']
    shots[-1] = shots[0]
    assert _run(packet) == 1
    shots.pop()
    assert _run(packet) == 1


@pytest.mark.parametrize('case', ['bytes-replaced', 'same-image-twice', 'wrong-viewport'])
def test_verify_png_bytes_not_just_row_metadata(packet, case):
    root, docs = packet
    row = docs['capture']['shots'][0]
    data = (root / 'dark-phone-z11.png').read_bytes() if case != 'wrong-viewport' else _png(0, 450, 600)
    (root / 'light-phone-z11.png').write_bytes(data)
    if case != 'bytes-replaced':
        row['png_sha256'] = _sha(data)
    assert _run(packet) == 1


def _ancestor(docs):
    docs['live']['merge'] = MERGE
    docs['live']['checks'][0]['reason'] = 'ancestor'


def test_pointer_merged_before_the_deployed_commit_is_bound_to_its_receipt(packet):
    _ancestor(packet[1])
    assert _run(packet, merge=MERGE) == 0


# Contract: a genuine live PASS for another pointer merge must not certify this candidate's pointer.
# Bug caught: receipt `merge` ignored, so an ancestor PASS for a historical pointer was accepted.
@pytest.mark.parametrize('case', ['other-receipt-merge', 'other-supplied-merge', 'equal-with-earlier-merge',
                                  'ancestor-with-same-merge', 'short-merge'])
def test_live_receipt_must_prove_this_candidates_pointer_merge(packet, case):
    docs, merge = packet[1], MERGE
    _ancestor(docs)
    if case == 'other-receipt-merge':
        docs['live']['merge'] = '5' * 40
    elif case == 'other-supplied-merge':
        merge = '5' * 40
    elif case == 'equal-with-earlier-merge':
        docs['live']['checks'][0]['reason'] = 'equal'
    elif case == 'ancestor-with-same-merge':
        docs['live']['merge'], merge = COMMIT, COMMIT
    else:
        merge = MERGE[:7]
    assert _run(packet, merge=merge) == 1


def _rechunk(png, edit):
    """Rebuild a PNG's chunks (type, data) after `edit`, recomputing every CRC."""
    chunks, pos = [], 8
    while pos < len(png):
        size = struct.unpack('>I', png[pos:pos + 4])[0]
        chunks.append((png[pos + 4:pos + 8], png[pos + 8:pos + 8 + size]))
        pos += 12 + size
    return b'\x89PNG\r\n\x1a\n' + b''.join(
        struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        for kind, data in edit(chunks))


def _bad_crc(png):
    return png[:41] + bytes([png[41] ^ 1]) + png[42:]  # first IDAT data byte


# Contract: the six-view packet only accepts screenshots that decode as a whole image.
# Bug caught: prefix/size/suffix-only check passed a PNG with junk chunks and no image data.
@pytest.mark.parametrize('case', ['no-image-data', 'junk-between-header-and-end', 'bad-crc', 'bad-zlib',
                                  'short-pixels', 'extra-pixels', 'trailing-bytes', 'truncated'])
def test_png_must_be_a_decodable_image_not_just_a_matching_frame(packet, case):
    root, docs = packet
    good = (root / 'light-phone-z11.png').read_bytes()
    if case == 'no-image-data':
        data = _rechunk(good, lambda c: [c[0], c[-1]])
    elif case == 'junk-between-header-and-end':
        data = _rechunk(good, lambda c: [c[0], (b'abcd', b'junk'), c[-1]])
    elif case == 'bad-crc':
        data = _bad_crc(good)
    elif case == 'bad-zlib':
        data = _rechunk(good, lambda c: [c[0], (b'IDAT', b'not zlib'), c[-1]])
    elif case == 'short-pixels':
        data = _rechunk(good, lambda c: [c[0], (b'IDAT', zlib.compress(b'\0' * 390)), c[-1]])
    elif case == 'extra-pixels':
        data = _rechunk(good, lambda c: [c[0], (b'IDAT', zlib.compress(b'\0' * (391 * 845))), c[-1]])
    elif case == 'trailing-bytes':
        data = good + b'x'
    else:
        data = good[:-20]
    (root / 'light-phone-z11.png').write_bytes(data)
    docs['capture']['shots'][0]['png_sha256'] = _sha(data)
    assert _run(packet) == 1


@pytest.mark.parametrize('case', ['wrong-stage', 'wrong-plan-worker', 'wrong-pointer', 'legacy-live',
                                  'wrong-survey', 'missing-contours', 'descendant-deploy', 'non-stage-worker'])
def test_capture_cannot_replace_independent_stage_and_candidate_proof(packet, case):
    root, docs = packet
    live = docs['live']
    origin = ORIGIN
    if case == 'wrong-stage':
        live['base'] = 'https://another-stage.example.workers.dev'
    elif case == 'wrong-plan-worker':
        docs['stage-plan']['worker'] = 'another-stage'
    elif case == 'wrong-pointer':
        with (root / 'pointer.json').open('ab') as stream:
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
