"""Verify the survey representation actually served to the Chart."""
import ctypes
from hashlib import sha256

from skippercast.relief.package import is_sha256


LIMITS = {'wire': 5 << 20, 'decoded': 16 << 20}


def binding(pointer):
    if 'survey_detail' not in pointer:
        return None
    pins = pointer['survey_detail']
    if (not isinstance(pins, dict) or pins.keys() != LIMITS.keys()
            or not is_sha256(pointer.get('envelope_sha256'))):
        raise ValueError('invalid reviewed survey binding in HEAD')
    for name, limit in LIMITS.items():
        rep = pins[name]
        if (not isinstance(rep, dict) or rep.keys() != {'bytes', 'sha256'}
                or type(rep['bytes']) is not int or not 0 < rep['bytes'] <= limit
                or not is_sha256(rep['sha256'])):
            raise ValueError('invalid reviewed survey binding in HEAD')
    return pins


def _decoded_reason(wire, expected):
    # Only decode authenticated wire bytes, and never allocate more than the
    # bounded output length from the reviewed pointer.
    try:
        decode = ctypes.CDLL('libbrotlidec.so.1').BrotliDecoderDecompress
    except (OSError, AttributeError):
        return 'decoder-unavailable'
    decode.argtypes = [ctypes.c_size_t, ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p]
    decode.restype = ctypes.c_int
    size = ctypes.c_size_t(expected['bytes'])
    output = ctypes.create_string_buffer(size.value)
    if (decode(len(wire), wire, ctypes.byref(size), output) != 1 or size.value != expected['bytes']
            or sha256(output).hexdigest() != expected['sha256']):
        return 'decoded-mismatch'
    return 'identical'


def check(pointer, pins, fetch):
    wire = pins['wire']
    key = (f'feeds/tiles/relief/{pointer["region"]}/{pointer["envelope_sha256"]}'
           f'/survey/{wire["sha256"]}.geojson.br')
    headers = {'Content-Encoding': 'br', 'Content-Length': str(wire['bytes']),
               'Content-Type': 'application/geo+json'}
    blocks = fetch(key, max_bytes=wire['bytes'], accept_encoding='br', expect_headers=headers)
    if blocks is None:
        reason = 'missing'
    else:
        data = b''.join(blocks)
        if len(data) != wire['bytes']:
            reason = 'wire-length'
        elif sha256(data).hexdigest() != wire['sha256']:
            reason = 'wire-sha256'
        else:
            reason = _decoded_reason(data, pins['decoded'])
    passed = reason == 'identical'
    return dict(check='survey', key=key, status='PASS' if passed else 'FAIL', reason=reason,
                **(pins if passed else {}))
