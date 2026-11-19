"""SCA-591: same-key cache controls. Run as a module for the read-only baseline.

The required test compares a populated retry with a clean render of each changed
request. The opt-in replay checks invalidation against those same expectations.
"""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.advisor import media_job as job
from tests.unit.test_advisor_media_job import FakeR2

PHOTO = {'id': 'photo', 'sha256': hashlib.sha256(b'blue').hexdigest(),
         'orientation': 1, 'mime': 'image/jpeg', 'r2_key': 'source',
         'keys': {k: f'{k}.jpg' for k in ('public', 'thumb', 'story')}}
GRAPHIC = {'id': 'graphic', 'kind': 'story', 'out_key': 'graphic.jpg',
           'media': [{'id': PHOTO['id'], 'public_key': 'public.jpg'}]}
SPEC = {'public': {'max_side': 8, 'quality': 80}, 'thumb': {'max_side': 4, 'quality': 80},
        'story': {'size': (12, 16), 'quality': 80}, 'daily': {}, 'renderer_version': 1}
CASES = [('photo', 'footer', {'story.jpg'}), ('photo', 'spec', {'public.jpg', 'story.jpg'}),
         ('graphic', 'footer', {'graphic.jpg'}), ('graphic', 'spec', {'graphic.jpg'}),
         ('graphic', 'photo', {'graphic.jpg'}), ('graphic', 'version', set())]


def _image(content, width=1, height=1):
    return SimpleNamespace(content=content, width=width, height=height)


def _story(spec, photo, number, *_args):
    return _image([photo.content, photo.width, number], *spec['story']['size'])


def _exercise(kind, change, *, clean_changed):
    # The recording renderer makes its inputs observable without Pillow/fonts.
    # Only rendering and storage are doubled; production owns both cache decisions.
    store = FakeR2({'source': (b'blue', {}), 'public.jpg': (b'blue', {})} if kind == 'graphic'
                   else {'source': (b'blue', {})})
    item = deepcopy(PHOTO if kind == 'photo' else GRAPHIC)
    derive = job.derive_media if kind == 'photo' else job.render_graphic
    keys = tuple(item['keys'].values()) if kind == 'photo' else (item['out_key'],)
    spec, footer = deepcopy(SPEC), None

    def run():
        store.puts.clear()
        derive(item, store, spec, footer, log=lambda _: None)
        return set(store.puts), {key: store.get(key) for key in keys}

    with patch.multiple(job, decode=lambda body, *_: _image(body.decode()),
                        fit=lambda image, size: _image(image.content, size, size),
                        story_image=_story,
                        jpeg=lambda image, quality: json.dumps([vars(image), quality]).encode()):
        writes, original = run()
        assert writes == set(keys), 'cold render must populate every output'
        repeat, same = run()
        assert not repeat and same == original, 'unchanged retry did not skip'
        if change == 'footer':
            footer = 'Fixture footer B'
        elif change == 'spec' and kind == 'photo':
            spec['public']['max_side'] = 6
        elif change == 'spec':
            spec['story']['size'] = (14, 16)
        elif change == 'photo':
            # Selected photo bytes change under the same media ID and object key.
            store.objects['public.jpg'] = (b'green', {job.META: hashlib.sha256(b'green').hexdigest()})
        elif change == 'version':
            spec['renderer_version'] = 2  # still requires a render, even if bytes match
        if clean_changed:
            for key in keys:
                del store.objects[key]
        writes, updated = run()
        return writes, {key for key in keys if updated[key] != original[key]}


@pytest.mark.parametrize('kind,change,changed_bytes', CASES)
def test_unchanged_retry_skips_and_cold_render_uses_effective_inputs(kind, change, changed_bytes):
    # If a changed input ceases to affect the intended output, this clean
    # control would no longer distinguish a stale cache hit from a render.
    writes, changed = _exercise(kind, change, clean_changed=True)
    assert changed == changed_bytes and changed <= writes


def _baseline():
    gap = False
    for kind, change, changed in CASES:
        writes, actual = _exercise(kind, change, clean_changed=False)
        required = changed or {'graphic.jpg'}  # version-only can produce identical bytes
        ok = required <= writes and actual == changed
        print(f'{kind}/{change}: {"PASS" if ok else "GAP"}; expected writes >= {sorted(required)}, '
              f'changed bytes {sorted(changed)}; observed writes {sorted(writes)}, changed bytes {sorted(actual)}')
        gap |= not ok
    return int(gap)


if __name__ == '__main__':
    raise SystemExit(_baseline())
