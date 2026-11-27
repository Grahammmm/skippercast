"""Immutable public survey objects, derived from release pins, not a caller URL.

A release may carry, next to the reviewed survey-detail pair, a small "gap" companion pair: the same
FeatureCollection with only its ``tier: none`` (no reviewed survey) features, in the detail's own canonical
JSON form. The Chart loads the companion at start so the existing no-survey hatch shows with Layers closed,
without fetching the whole detail. It is never a separate survey claim: the ``survey_gap`` stage derives it
byte-exactly from the detail its upstream receipt attests (``gap_document``), packaging re-checks that
derivation, and its features can only say "no survey".
"""
import ctypes
import hashlib
import json

PREFIX = 'layers/public/survey-detail/'
DECODED_PATH = PREFIX + 'detail.geojson'
WIRE_PATH = PREFIX + 'detail.geojson.br'
# The survey_gap stage's own target (a sibling, so neither stage's write-then-rename moves the other's files).
GAP_PREFIX = 'layers/public/survey-gap/'
GAP_DECODED_PATH = GAP_PREFIX + 'gap.geojson'
GAP_WIRE_PATH = GAP_PREFIX + 'gap.geojson.br'
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


def _document(decoded: bytes) -> dict:
    """A reviewed decoded detail (or companion) as a document, refused unless it is canonical."""
    try:
        doc = json.loads(decoded.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise ValueError('survey detail is not JSON') from None
    if (not isinstance(doc, dict) or doc.get('type') != 'FeatureCollection'
            or not isinstance(doc.get('features'), list) or _canonical(doc) != decoded):
        raise ValueError('survey detail is not a canonical FeatureCollection')
    return doc


def gap_document(decoded: bytes) -> bytes:
    """The companion for a reviewed decoded detail: the same document, keeping only its tier-none features."""
    doc = _document(decoded)
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


def detail_document(zone_detail: bytes, region: str, source_ids: dict) -> bytes:
    """The public survey detail for a region's zone-stage detail, in canonical form.

    ``source_ids`` maps every included public selection file id to its catalog source id. A surveyed feature must
    name exactly one catalog source, either directly or through one of its selection files; the Chart refuses
    anything else. A no-survey (``tier: none``) feature names none. Nothing else in the document changes.
    """
    try:
        doc = json.loads(zone_detail.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise ValueError('zone detail is not JSON') from None
    if (not isinstance(doc, dict) or doc.get('type') != 'FeatureCollection' or not isinstance(doc.get('features'), list)
            or doc.get('region') != region or doc.get('navigation') != 'NOT FOR NAVIGATION'):
        raise ValueError(f'zone detail is not the {region} survey FeatureCollection')
    catalog = set(source_ids.values())
    for feature in doc['features']:
        props = feature.get('properties') if isinstance(feature, dict) else None
        if not isinstance(props, dict) or not isinstance(props.get('sources'), list):
            raise ValueError('zone detail feature without a sources list')
        if props.get('tier') == 'none':
            if props['sources']:
                raise ValueError('a no-survey feature cannot name a source')
            continue
        named = []
        for value in props['sources']:
            source = source_ids.get(value, value if value in catalog else None)
            if source is None:
                raise ValueError(f'zone detail names a source outside the public selection: {value!r}')
            if source not in named:
                named.append(source)
        if len(named) != 1:
            raise ValueError('a surveyed feature must name exactly one catalog source')
        props['sources'] = named
    return _canonical(doc)


def check_detail_sources(decoded: bytes, source_ids) -> None:
    """The Chart draws a survey detail only if each surveyed area names exactly one of the release's own sources.

    ``source_ids`` are the release (and so the pointer) source ids; ``decodeSurveyDetail`` drops the whole layer for
    any other name, so a release must not carry such a detail. A no-survey feature names none."""
    for feature in _document(decoded)['features']:
        props = feature.get('properties') if isinstance(feature, dict) else None
        if not isinstance(props, dict):
            raise ValueError('survey detail feature without properties')
        sources = props.get('sources')
        if props.get('tier') == 'none':
            if sources != []:
                raise ValueError('a no-survey feature cannot name a source')
        elif not (isinstance(sources, list) and len(sources) == 1 and sources[0] in source_ids):
            raise ValueError(f'survey detail names a source the release does not credit: {sources!r}')


def check_gap(detail: bytes, gap: bytes) -> None:
    if gap_document(detail) != gap:
        raise ValueError('survey gap companion is not derived from the reviewed survey detail')


def is_survey_path(path: str) -> bool:
    """A release layer that belongs to the survey representation (detail or gap companion)."""
    return path.startswith((PREFIX, GAP_PREFIX))


def pointer_members(rows: dict) -> dict:
    """Map the release's survey layer rows ({path: {bytes, sha256, ...}}) to pointer members."""
    paths = frozenset(path for path in rows if is_survey_path(path))
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
