"""Portable, wholly synthetic save-shaped inventory and in-memory transport."""
import hashlib
import io
import json

PAYLOAD = b'{"synthetic":true}\n'
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
CACHE = 'cache/' + 'a' * 64 + '/source.tif'


def row(path, **changes):
    value = {'path': path, 'sha256': DIGEST, 'bytes': len(PAYLOAD)}
    value.update(changes)
    return value


def inventory(scope, files):
    return {'version': 1, 'scope': scope, 'files': files}


class Missing(Exception):
    response = {'Error': {'Code': 'NoSuchKey'}}


class MemoryS3:
    """Only explicitly seeded in-memory objects; no client or credential lookup."""
    def __init__(self, document=None, scope='shared'):
        self.objects = {}
        self.calls = []
        self.fail_key = None
        if document is not None:
            self.objects[f'seafloor-cache/state/{scope}.json'] = json.dumps(document).encode()

    def get_object(self, *, Bucket, Key):
        self.calls.append(Key)
        if Key == self.fail_key:
            raise OSError('synthetic transfer failure')
        if Key not in self.objects:
            raise Missing()
        return {'Body': io.BytesIO(self.objects[Key])}

    def head_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise Missing()
        return {}

    def put_object(self, *, Bucket, Key, Body, **metadata):
        self.objects[Key] = Body.read() if hasattr(Body, 'read') else Body
