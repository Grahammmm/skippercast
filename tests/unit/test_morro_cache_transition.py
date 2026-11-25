"""Cache-transition reader (M26): a warm phone is accepted on the target generation only when the shell, the
/sources credits, BOTH contour zoom bands and the served bytes all match it; new shell + credits over one stale
band is rejected."""
import json

import pytest

from scripts.relief import morro_cache_transition as ct

V1 = {'build': '7b1399c64d', 'pointer': None, 'detail': 'd1' * 32, 'overview': 'o1' * 32, 'sources': 's1' * 32}
V2 = {'build': '37a37b16d2', 'pointer': 'p2' * 32, 'detail': 'd2' * 32, 'overview': 'o2' * 32, 'sources': 's2' * 32}
PTR, DET, OVR = ct.POINTER_PATH, ct.BAND_PATHS['detail'], ct.BAND_PATHS['overview']


def visit(name, gen, zoom, contour, drawn, pointer=None):
    """One saved phone visit: page build, the contour file it got for its band, the pointer response if any."""
    band_path = DET if zoom >= 13 else OVR
    band = 'detail' if zoom >= 13 else 'overview'
    fetches = []
    if pointer is not None:
        fetches.append({'path': PTR, 'status': pointer, 'sha256': V2['pointer'] if pointer == 200 else None})
    fetches.append({'path': band_path, 'status': 200, 'sha256': contour[band]})
    return {'name': name, 'build': gen['build'], 'zoom': zoom, 'fetches': fetches, 'contours_drawn': str(drawn)}


def doc(direction, visits, sources=None, served=None, after=None):
    target, previous = (V2, V1) if direction == 'update' else (V1, V2)
    return {'schema': ct.SCHEMA, 'direction': direction, 'target': dict(target), 'previous': dict(previous),
            'visits': visits, 'sources_sha256': target['sources'] if sources is None else sources,
            'sources_after_visits': len(visits) if after is None else after,
            'served': dict(target) if served is None else served}


# The M24 observations, reduced: update v1 -> v2 and rollback v2 -> v1 on one SW-controlled phone.
UP = [
    visit('up_now', V2, 15, V1, 9),                 # v2 shell, old live lines from the HTTP cache, no pointer asked
    visit('up_after_wait', V2, 15, V1, 9),
    visit('up_final', V2, 15, V2, 5, pointer=200),  # z15 recovered past max-age + one SWR load
    visit('up_final_z11', V2, 11, V2, 5, pointer=200),
]
BACK = [
    visit('back_now', V1, 15, V2, 0, pointer=404),  # v1 shell, cached ft-v3 detail, no pointer -> "did not load"
    visit('back_final', V1, 15, V1, 9),             # z15 recovered
    visit('back_final_z11', V1, 11, V2, 0, pointer=404),  # first z11 load: overview still cached v2
    visit('back_final2_z11', V1, 11, V1, 69),       # second z11 load: v1 overview
]


def test_update_accepts_only_with_both_bands_fresh():
    assert ct.judge(doc('update', UP)) == {
        'direction': 'update', 'verdict': 'ACCEPT', 'reasons': [],
        'bands': {'detail': {'visit': 'up_final', 'generation': 'target', 'drawn': 5, 'pointer': 200, 'problems': []},
                  'overview': {'visit': 'up_final_z11', 'generation': 'target', 'drawn': 5, 'pointer': 200, 'problems': []}}}


def test_new_shell_and_credits_over_stale_detail_rejected():
    result = ct.judge(doc('update', UP[:2]))
    assert result['verdict'] == 'REJECT'
    assert result['reasons'] == ['stale-band:detail', 'pointer-band:detail', 'band-not-observed:overview']


def test_fresh_detail_does_not_prove_overview():
    assert ct.judge(doc('update', UP[:3]))['reasons'] == ['band-not-observed:overview']


def test_rollback_z15_recovery_with_one_stale_overview_rejected():
    result = ct.judge(doc('rollback', BACK[:3]))
    assert result['verdict'] == 'REJECT'
    assert result['reasons'] == ['stale-band:overview', 'not-drawn-band:overview']
    assert result['bands']['detail']['problems'] == []


def test_rollback_second_z11_load_accepts():
    result = ct.judge(doc('rollback', BACK))
    assert result['verdict'] == 'ACCEPT' and result['bands']['overview']['visit'] == 'back_final2_z11'


def test_timeline_first_accept_is_the_second_z11_load():
    rows = ct.timeline(doc('rollback', BACK))
    assert [r['verdict'] for r in rows] == ['REJECT', 'REJECT', 'REJECT', 'ACCEPT']


def test_stale_credits_rejected_even_with_fresh_bands():
    assert ct.judge(doc('update', UP, sources=V1['sources']))['reasons'] == ['sources-not-target']
    assert ct.judge(doc('update', UP, sources=''))['reasons'] == ['sources-not-read']


def test_old_shell_on_last_visit_rejected():
    stale_shell = UP + [visit('up_old_shell', V1, 15, V2, 5, pointer=200)]
    reasons = ct.judge(doc('update', stale_shell))['reasons']
    assert 'shell-not-target' in reasons and 'shell-band:detail' in reasons


@pytest.mark.parametrize('key', ['pointer', 'detail', 'overview', 'sources', 'build'])
def test_served_bytes_must_match_target(key):
    served = dict(V2, **{key: V1[key] if V1[key] else 'x' * 64})
    assert ct.judge(doc('update', UP, served=served))['reasons'] == [f'served-mismatch:{key}']


def test_served_readback_required():
    d = doc('update', UP)
    d['served'] = None
    assert ct.judge(d)['reasons'] == ['served-not-read']


def test_wrong_pointer_bytes_rejected():
    bad = [dict(v, fetches=[dict(f, sha256='f' * 64) if f['path'] == PTR else f for f in v['fetches']]) for v in UP]
    reasons = ct.judge(doc('update', bad))['reasons']
    assert 'pointer-band:detail' in reasons and 'pointer-band:overview' in reasons
    assert any(r.startswith('unsafe:up_final:') for r in reasons)


def test_ft_v3_drawn_without_pointer_is_unsafe_on_any_visit():
    unsafe = [visit('back_now', V1, 15, V2, 3, pointer=404)] + BACK[1:]
    result = ct.judge(doc('rollback', unsafe))
    assert result['verdict'] == 'REJECT'
    assert result['reasons'] == ['unsafe:back_now:pointer-bound-detail-drawn-without-pointer']


def test_rollback_target_must_not_serve_a_pointer():
    leaked = BACK[:3] + [visit('back_final2_z11', V1, 11, V1, 69, pointer=200)]
    assert ct.judge(doc('rollback', leaked))['reasons'] == ['pointer-band:overview']


@pytest.mark.parametrize('status', [403, 500, 302, 0])
def test_rollback_pointer_absence_needs_exactly_404(status):
    """RETURN #3777 item 2: only no pointer response or HTTP 404 proves the pointer is gone."""
    odd = BACK[:3] + [visit('back_final2_z11', V1, 11, V1, 69, pointer=status)]
    assert ct.judge(doc('rollback', odd))['reasons'] == ['pointer-band:overview']
    ok = BACK[:3] + [visit('back_final2_z11', V1, 11, V1, 69, pointer=404)]
    assert ct.judge(doc('rollback', ok))['verdict'] == 'ACCEPT'


def test_unsafe_scan_reads_both_contour_files_of_a_visit():
    """RETURN #3777 item 1: a visit that fetched both files counts as detail, but a pointer-bound overview it
    drew without the pointer must still be caught, even when a later fresh pair would otherwise ACCEPT."""
    mixed = visit('back_mixed', V1, 15, V1, 9, pointer=404)
    mixed['fetches'].insert(0, {'path': OVR, 'status': 200, 'sha256': V2['overview']})
    assert ct.visit_band(mixed) == 'detail'
    result = ct.judge(doc('rollback', [mixed] + BACK))
    assert result['reasons'] == ['unsafe:back_mixed:pointer-bound-overview-drawn-without-pointer']
    held = dict(mixed, contours_drawn='0')  # nothing drawn: the "did not load" window is safe
    assert ct.judge(doc('rollback', [held] + BACK))['verdict'] == 'ACCEPT'


def test_timeline_counts_credits_only_after_they_were_read():
    """RETURN #3777 item 3: the /sources readback is bound to its place in the timeline."""
    rows = ct.timeline(doc('update', UP, after=len(UP) + 0))
    assert rows[-1]['verdict'] == 'ACCEPT'
    assert 'sources-not-read' not in rows[-1]['reasons']
    late = doc('update', UP + [visit('up_more', V2, 11, V2, 5, pointer=200)], after=5)
    rows = ct.timeline(late)
    assert [r['verdict'] for r in rows] == ['REJECT', 'REJECT', 'REJECT', 'REJECT', 'ACCEPT']
    assert rows[3]['reasons'] == ['sources-not-read']  # both bands fresh at visit 4, credits not read until after 5
    assert ct.judge(late)['verdict'] == 'ACCEPT'


@pytest.mark.parametrize('after', [None, -1, 5, True, '4'])
def test_credits_readback_needs_its_position(after):
    d = doc('update', UP)
    d['sources_after_visits'] = after
    with pytest.raises(ct.Unusable, match='sources_after_visits'):
        ct.judge(d)


def test_foreign_and_missing_contours_rejected():
    foreign = UP[:3] + [dict(visit('up_final_z11', V2, 11, V2, 5, pointer=200))]
    foreign[-1]['fetches'][-1]['sha256'] = 'e' * 64
    assert ct.judge(doc('update', foreign))['reasons'] == ['foreign-band:overview']
    missing = UP[:3] + [dict(visit('up_final_z11', V2, 11, V2, 5, pointer=200))]
    missing[-1]['fetches'][-1]['status'] = 404
    assert ct.judge(doc('update', missing))['reasons'] == ['missing-band:overview']


def test_band_from_fetch_then_zoom():
    assert ct.visit_band({'fetches': [{'path': OVR}], 'zoom': 15}) == 'overview'
    assert ct.visit_band({'fetches': [], 'zoom': 13}) == 'detail'
    assert ct.visit_band({'fetches': [], 'zoom': 12}) == 'overview'
    assert ct.visit_band({'fetches': []}) is None


@pytest.mark.parametrize('mutate, message', [
    (lambda d: d.update(schema='other/1'), 'schema'),
    (lambda d: d.update(direction='sideways'), 'direction'),
    (lambda d: d['target'].update(overview=V1['overview']), 'share overview'),
    (lambda d: d['target'].update(pointer=None), 'exactly one generation'),
    (lambda d: d['target'].pop('sources'), 'identity needs'),
    (lambda d: d.update(visits={}), 'visits'),
])
def test_unusable_input_gives_no_verdict(mutate, message):
    d = doc('update', UP)
    mutate(d)
    with pytest.raises(ct.Unusable, match=message):
        ct.judge(d)


def _m24_row(theme, back_visits):
    def ref(gen, zoom, drawn):
        fetches = ([{'path': PTR, 'status': 200, 'sha256': gen['pointer']}] if gen['pointer'] else []) + [
            {'path': DET if zoom >= 13 else OVR, 'status': 200, 'sha256': gen['detail' if zoom >= 13 else 'overview']}]
        return {'build': gen['build'], 'zoom': zoom, 'fetches': fetches, 'contours_drawn': str(drawn),
                'sources': {'status': 200, 'sha256': gen['sources']}}
    visits = {}
    for i, v in enumerate(UP):
        visits[v['name']] = dict(v, at_ms=1000 + (i + 1) * 10_000)
    for i, v in enumerate(back_visits):
        visits[v['name']] = dict(v, at_ms=500_000 + (i + 1) * 10_000)
    return {'theme': theme,
            'ref': {'v1_z15': ref(V1, 15, 9), 'v1_z11': ref(V1, 11, 69), 'v2_z15': ref(V2, 15, 5), 'v2_z11': ref(V2, 11, 5)},
            'session': {'visits': visits, 'switch_up_ms': 1000, 'switch_back_ms': 500_000,
                        'sources': {'up': {'sha256': V2['sources']}, 'back': {'sha256': V1['sources']}}}}


RECEIPT = {'builds': {'v1': V1['build'], 'v2': V2['build']},
           'want': {k: {'pointer': g['pointer'], 'detail': g['detail'], 'overview': g['overview']} for k, g in (('v1', V1), ('v2', V2))},
           'want_sources': {'v1': V1['sources'], 'v2': V2['sources']}}


def test_m24_adapter_splits_directions_and_reads_served_from_cold_refs():
    up, back = ct.from_m24(_m24_row('light', BACK), RECEIPT)
    assert (up['label'], back['label']) == ('light-update', 'light-rollback')
    assert up['served'] == V2 and back['served'] == V1
    assert [v['name'] for v in back['visits']] == [v['name'] for v in BACK]
    assert [v['t_after_switch_s'] for v in up['visits']] == [10, 20, 30, 40]
    assert ct.judge(up)['verdict'] == ct.judge(back)['verdict'] == 'ACCEPT'


def test_cli_exit_codes(tmp_path, capsys):
    good, short = tmp_path / 'phone-good.json', tmp_path / 'phone-short.json'
    receipt, single, bad = tmp_path / 'receipt.json', tmp_path / 'one.json', tmp_path / 'bad.json'
    good.write_text(json.dumps([_m24_row('light', BACK), _m24_row('dark', BACK)]))
    short.write_text(json.dumps([_m24_row('light', BACK), _m24_row('dark', BACK[:3])]))  # one z11 load only
    receipt.write_text(json.dumps(RECEIPT))
    single.write_text(json.dumps(doc('update', UP[:2])))
    bad.write_text(json.dumps(dict(doc('update', UP), schema='nope')))
    assert ct.main([str(good), '--m24', str(receipt)]) == 0
    capsys.readouterr()
    assert ct.main([str(short), '--m24', str(receipt)]) == 1
    out = capsys.readouterr().out
    dark_back = [r for r in json.loads(out) if r['label'] == 'dark-rollback'][0]
    assert dark_back['final']['reasons'] == ['stale-band:overview', 'not-drawn-band:overview']
    assert ct.main([str(single)]) == 1
    assert ct.main([str(bad)]) == 2
    assert ct.main([str(tmp_path / 'missing.json')]) == 2


@pytest.mark.parametrize('content', [[], {}, 'rows'])
def test_cli_empty_m24_input_is_unusable(tmp_path, content):
    """RETURN #3777 item 4: no theme rows is no evidence, not a pass."""
    phone, receipt = tmp_path / 'phone.json', tmp_path / 'receipt.json'
    phone.write_text(json.dumps(content))
    receipt.write_text(json.dumps(RECEIPT))
    assert ct.main([str(phone), '--m24', str(receipt)]) == 2


def test_cli_m24_direction_without_visits_is_unusable(tmp_path):
    row = _m24_row('light', BACK)
    row['session']['visits'] = {k: v for k, v in row['session']['visits'].items() if not k.startswith('back')}
    phone, receipt = tmp_path / 'phone.json', tmp_path / 'receipt.json'
    phone.write_text(json.dumps([row]))
    receipt.write_text(json.dumps(RECEIPT))
    assert ct.main([str(phone), '--m24', str(receipt)]) == 2
