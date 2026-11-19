"""SCA-591/SCA-444: same-key cache controls. Run as a module for the cache replay.

Each retry must match a clean render of the same inputs without rewriting
unaffected photo derivatives.
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
           'media': [{**{k: PHOTO[k] for k in ('id', 'r2_key', 'mime', 'orientation')},
                      'public_key': 'public.jpg'}]}
SPEC = {'public': {'max_side': 8, 'quality': 80}, 'thumb': {'max_side': 4, 'quality': 80},
        'story': {'size': (12, 16), 'quality': 80}, 'daily': {}, 'renderer_version': 1,
        'footer': {'text': 'Fixture', 'fallback': 'Fixture footer A'}}
CASES = [('photo', 'footer', {'story.jpg'}), ('photo', 'spec', {'public.jpg', 'story.jpg'}),
         ('graphic', 'footer', {'graphic.jpg'}), ('graphic', 'spec', {'graphic.jpg'}),
         ('graphic', 'photo', {'graphic.jpg'}), ('graphic', 'fallback', {'graphic.jpg'}),
         ('graphic', 'version', set()), ('photo', 'version', set())]


def _image(content, width=1, height=1):
    return SimpleNamespace(content=content, width=width, height=height)


def _story(spec, photo, number, *_args):
    footer = job.display_number(number) or spec['footer']['fallback']
    return _image([photo.content, photo.width, footer], *spec['story']['size'])


def _exercise(kind, change, *, clean_changed):
    # The recording renderer makes its inputs observable without Pillow/fonts.
    # Only rendering and storage are doubled; production owns both cache decisions.
    store = FakeR2({'source': (b'blue', {}), 'public.jpg': (b'blue', {})} if kind == 'graphic' and change != 'fallback'
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
        footer = '  '  # same effective footer as None
        repeat, same = run()
        assert not repeat and same == original, 'equivalent footer did not skip'
        if change == 'footer':
            footer = 'Fixture footer B'
        elif change == 'spec' and kind == 'photo':
            spec['public']['max_side'] = 6
        elif change == 'spec':
            spec['story']['size'] = (14, 16)
        elif change == 'photo':
            # Same ID, key and metadata: the selected derivative's bytes changed.
            store.objects['public.jpg'] = (b'green', {})
        elif change == 'fallback':
            spec['public']['max_side'] = 6  # only affects a graphic using the original
        elif change == 'version':
            spec['renderer_version'] = 2  # still requires a render, even if bytes match
        if clean_changed:
            for key in keys:
                del store.objects[key]
        writes, updated = run()
        repeat, same = run()
        assert not repeat and same == updated, 'retry with the new inputs did not skip'
        return writes, {key for key in keys if updated[key] != original[key]}, updated


def _expected_writes(kind, changed):
    return changed or ({'graphic.jpg'} if kind == 'graphic' else set(PHOTO['keys'].values()))


@pytest.mark.parametrize('kind,change,changed_bytes', CASES)
def test_render_cache_matches_clean_render_and_only_rewrites_affected_outputs(kind, change, changed_bytes):
    # A retry must not preserve stale art (or rewrite unrelated derivatives).
    writes, changed, clean = _exercise(kind, change, clean_changed=True)
    assert changed == changed_bytes and changed <= writes
    writes, changed, cached = _exercise(kind, change, clean_changed=False)
    assert writes == _expected_writes(kind, changed_bytes)
    assert changed == changed_bytes and cached == clean


def _baseline():
    gap = False
    for kind, change, changed in CASES:
        writes, actual, _ = _exercise(kind, change, clean_changed=False)
        required = _expected_writes(kind, changed)  # version-only can produce identical bytes
        ok = required == writes and actual == changed
        print(f'{kind}/{change}: {"PASS" if ok else "GAP"}; expected writes {sorted(required)}, '
              f'changed bytes {sorted(changed)}; observed writes {sorted(writes)}, changed bytes {sorted(actual)}')
        gap |= not ok
    return int(gap)


if __name__ == '__main__':
    raise SystemExit(_baseline())
