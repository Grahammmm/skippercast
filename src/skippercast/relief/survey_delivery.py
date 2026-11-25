"""Immutable public survey object, derived from release pins, not a caller URL."""
import ctypes
import hashlib

WIRE_PATH = 'layers/public/survey-detail/detail.geojson.br'
WIRE_LIMIT = 5 << 20
DECODED_LIMIT = 16 << 20


def key(region, envelope_sha, wire_sha):
    return f'tiles/relief/{region}/{envelope_sha}/survey/{wire_sha}.geojson.br'


def check_decoded(path, pins):
    # Call only after the wire checksum is verified. Preallocate at the reviewed bound.
    n = pins['decoded']['bytes']
    if not 0 < n <= DECODED_LIMIT or not 0 < path.stat().st_size <= WIRE_LIMIT:
        raise ValueError('survey exceeds size bound')
    fn = decoder()
    raw = path.read_bytes()
    buf, actual = ctypes.create_string_buffer(n), ctypes.c_size_t(n)
    if (fn(len(raw), raw, ctypes.byref(actual), buf) != 1 or actual.value != n
            or hashlib.sha256(buf.raw).hexdigest() != pins['decoded']['sha256']):
        raise ValueError('decoded survey does not match reviewed pins')


def decoder():
    try:
        fn = ctypes.CDLL('libbrotlidec.so.1').BrotliDecoderDecompress
    except (OSError, AttributeError):
        raise ValueError('survey verification requires libbrotlidec.so.1') from None
    fn.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p]
    fn.restype = ctypes.c_int
    return fn
