"""Immutable public survey objects, derived from release pins, not a caller URL.

A release may carry, next to the reviewed survey-detail pair, a small "gap" companion pair: the same
FeatureCollection with only its ``tier: none`` (no reviewed survey) features, in the detail's own canonical
JSON form. The Chart loads the companion at start so the existing no-survey hatch shows with Layers closed,
without fetching the whole detail. It is never a separate survey claim: it must be byte-derived from the
packaged detail (``gap_document``), and its features can only say "no survey".
"""
import ctypes
import hashlib
import json
import sys
from pathlib import Path

PREFIX = 'layers/public/survey-detail/'
DECODED_PATH = PREFIX + 'detail.geojson'
WIRE_PATH = PREFIX + 'detail.geojson.br'
GAP_DECODED_PATH = PREFIX + 'gap.geojson'
GAP_WIRE_PATH = PREFIX + 'gap.geojson.br'
WIRE_LIMIT = 5 << 20
DECODED_LIMIT = 16 << 20
# The companion is drawn at start for every visitor of the region, so it stays small.
GAP_WIRE_LIMIT = 256 << 10
GAP_DECODED_LIMIT = 2 << 20
# Release layer paths -> (pointer member, representation). A release has no pair, the detail pair, or both pairs.
MEMBERS = {DECODED_PATH: ('survey_detail', 'decoded'), WIRE_PATH: ('survey_detail', 'wire'),
           GAP_DECODED_PATH: ('survey_gap', 'decoded'), GAP_WIRE_PATH: ('survey_gap', 'wire')}
SHAPES = (frozenset(), frozenset({DECODED_PATH, WIRE_PATH}), frozenset(MEMBERS))
LIMITS = {'survey_detail': (WIRE_LIMIT, DECODED_LIMIT), 'survey_gap': (GAP_WIRE_LIMIT, GAP_DECODED_LIMIT)}


def key(region, envelope_sha, wire_sha):
    # Content-addressed: the companion's wire digest differs from the detail's, so both share the prefix.
    return f'tiles/relief/{region}/{envelope_sha}/survey/{wire_sha}.geojson.br'


def check_decoded(path, pins, *, wire_limit=WIRE_LIMIT, decoded_limit=DECODED_LIMIT):
    """Return the decoded bytes once they match the pins. Call only after the wire checksum is verified."""
    # Preallocate at the reviewed bound.
    n = pins['decoded']['bytes']
    if not 0 < n <= decoded_limit or not 0 < path.stat().st_size <= wire_limit:
        raise ValueError('survey exceeds size bound')
    fn = decoder()
    raw = path.read_bytes()
    buf, actual = ctypes.create_string_buffer(n), ctypes.c_size_t(n)
    if (fn(len(raw), raw, ctypes.byref(actual), buf) != 1 or actual.value != n
            or hashlib.sha256(buf.raw).hexdigest() != pins['decoded']['sha256']):
        raise ValueError('decoded survey does not match reviewed pins')
    return buf.raw


def decoder():
    try:
        fn = ctypes.CDLL('libbrotlidec.so.1').BrotliDecoderDecompress
    except (OSError, AttributeError):
        raise ValueError('survey verification requires libbrotlidec.so.1') from None
    fn.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p]
    fn.restype = ctypes.c_int
    return fn


def _canonical(doc) -> bytes:
    # The reviewed detail's own serialization: sorted keys, no spaces, ASCII escapes, one trailing newline.
    return (json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def gap_document(decoded: bytes) -> bytes:
    """The companion for a reviewed decoded detail: the same document, keeping only its tier-none features."""
    try:
        doc = json.loads(decoded.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise ValueError('survey detail is not JSON') from None
    if (not isinstance(doc, dict) or doc.get('type') != 'FeatureCollection'
            or not isinstance(doc.get('features'), list) or _canonical(doc) != decoded):
        raise ValueError('survey detail is not a canonical FeatureCollection')
    gap = []
    for feature in doc['features']:
        props = feature.get('properties') if isinstance(feature, dict) else None
        if not isinstance(props, dict):
            raise ValueError('survey detail feature without properties')
        if props.get('tier') == 'none':
            if props.get('sources') != []:
                raise ValueError('a no-survey feature cannot name a source')
            gap.append(feature)
    if not gap:
        raise ValueError('survey detail has no tier-none area; ship no gap companion')
    if len(gap) == len(doc['features']):
        raise ValueError('survey detail is all no-survey area; the detail alone is the cue')
    return _canonical(dict(doc, features=gap))


def check_gap(detail: bytes, gap: bytes) -> None:
    if gap_document(detail) != gap:
        raise ValueError('survey gap companion is not derived from the reviewed survey detail')


def pointer_members(rows: dict) -> dict:
    """Map the release's survey layer rows ({path: {bytes, sha256, ...}}) to pointer members."""
    paths = frozenset(path for path in rows if path.startswith(PREFIX))
    if paths not in SHAPES:
        raise ValueError('incomplete or unexpected public survey representation')
    members = {}
    for path in sorted(paths):
        member, kind = MEMBERS[path]
        members.setdefault(member, {})[kind] = {k: rows[path][k] for k in ('bytes', 'sha256')}
    for member, (wire, decoded) in LIMITS.items():
        if member in members and (members[member]['wire']['bytes'] > wire or members[member]['decoded']['bytes'] > decoded):
            raise ValueError(f'{member} exceeds its size bound')
    if 'survey_gap' in members and any(members['survey_gap'][kind]['sha256'] == members['survey_detail'][kind]['sha256']
                                       for kind in ('wire', 'decoded')):
        raise ValueError('survey gap companion repeats the survey detail; ship the detail alone')
    return members


def encode(raw: bytes) -> bytes:
    """Brotli (quality 11, text mode) through the system encoder, for the producer only."""
    try:
        lib = ctypes.CDLL('libbrotlienc.so.1')
    except OSError:
        raise ValueError('survey encoding requires libbrotlienc.so.1') from None
    bound = lib.BrotliEncoderMaxCompressedSize
    bound.argtypes, bound.restype = [ctypes.c_size_t], ctypes.c_size_t
    fn = lib.BrotliEncoderCompress
    fn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_size_t, ctypes.c_char_p,
                   ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p]
    fn.restype = ctypes.c_int
    size = ctypes.c_size_t(bound(len(raw)) or len(raw) + 1024)
    out = ctypes.create_string_buffer(size.value)
    if fn(11, 22, 1, len(raw), raw, ctypes.byref(size), out) != 1:
        raise ValueError('survey encoding failed')
    return out.raw[:size.value]


def write_gap(layer_dir: Path) -> dict:
    """Producer step: write gap.geojson(.br) next to a verified detail pair in the survey-detail leaf."""
    detail = (layer_dir / 'detail.geojson').read_bytes()
    pins = {'decoded': {'bytes': len(detail), 'sha256': hashlib.sha256(detail).hexdigest()}}
    check_decoded(layer_dir / 'detail.geojson.br', pins)  # the wire must be this exact detail
    gap = gap_document(detail)
    gap_wire = encode(gap)
    if len(gap) > GAP_DECODED_LIMIT or len(gap_wire) > GAP_WIRE_LIMIT:
        raise ValueError('survey gap companion exceeds its size bound')
    (layer_dir / 'gap.geojson').write_bytes(gap)
    (layer_dir / 'gap.geojson.br').write_bytes(gap_wire)
    return {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            for name, data in (('gap.geojson', gap), ('gap.geojson.br', gap_wire))}


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != 'gap':
        print('usage: survey_delivery.py gap SURVEY_DETAIL_LAYER_DIR', file=sys.stderr)
        return 2
    try:
        print(json.dumps(write_gap(Path(args[1])), sort_keys=True))
    except (OSError, ValueError) as exc:
        print(f'survey gap held: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
