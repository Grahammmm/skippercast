"""Ordered four-window schedule: the coordinator's decision sequence is the authority.

The 2026-10-11 four128 attempt stopped at A-map with "action differs from current
bounded ordered decision". Its driver walked A..D serially (acquire, qualify, map per
window), but ``select_next`` pipelines native work under two backlog bounds (at most
one acquired-but-unqualified window, at most two qualified-but-unmapped windows):
after A-qualify the decision is B-acquire, not A-map. ``Controller.step`` correctly
refuses an off-decision action, so the fix belongs in the driver (follow
``status.next``), and these tests pin the coordinator sequence that driver follows.
"""
from skippercast.coastal.coordinator.ordered_trial import select_next

NOW = 1_000_000.0
PREPARATION = {'deadline_epoch': NOW + 3600, 'source_cutoff_epoch': NOW + 2400}


def _walk(preparation, now=NOW):
    rows = [{} for _ in range(4)]
    order = []
    for _ in range(13):
        decision = select_next(preparation, rows, now)
        if decision['state'] != 'ready':
            return order, decision
        key = 'ABCD'[decision['index']] + '-' + decision['stage']
        assert key not in order, key
        order.append(key)
        rows[decision['index']][decision['stage']] = 'done'
    raise AssertionError('schedule did not terminate')


def test_full_four_window_order_is_pipelined_and_complete():
    order, final = _walk(PREPARATION)
    assert final == {'state': 'complete'}
    assert order == ['A-acquire', 'A-qualify', 'B-acquire', 'B-qualify', 'A-map',
                     'C-acquire', 'C-qualify', 'B-map', 'D-acquire', 'D-qualify',
                     'C-map', 'D-map']


def test_after_a_qualify_the_decision_is_b_acquire_not_a_map():
    # The exact state the 2026-10-11 A-map action met.
    rows = [{'acquire': 'done', 'qualify': 'done'}, {}, {}, {}]
    assert select_next(PREPARATION, rows, NOW) == {'state': 'ready', 'stage': 'acquire', 'index': 1}


def test_backlog_bounds_are_never_exceeded_along_the_walk():
    rows = [{} for _ in range(4)]
    for _ in range(12):
        decision = select_next(PREPARATION, rows, NOW)
        rows[decision['index']][decision['stage']] = 'done'
        acquired = [r for r in rows if r.get('acquire') == 'done' and r.get('qualify') != 'done']
        waiting = [r for r in rows if r.get('qualify') == 'done' and r.get('map') != 'done']
        assert len(acquired) <= 1 and len(waiting) <= 2


def test_native_cutoff_drains_qualified_windows_to_map():
    rows = [{'acquire': 'done', 'qualify': 'done'}, {}, {}, {}]
    late = PREPARATION['source_cutoff_epoch'] - 100
    assert select_next(PREPARATION, rows, late) == {'state': 'ready', 'stage': 'map', 'index': 0}
    assert select_next(PREPARATION, [{}, {}, {}, {}], late) == {'state': 'native_cutoff'}


def test_deadline_and_common_failure_stop_the_schedule():
    assert select_next(PREPARATION, [{}, {}, {}, {}], PREPARATION['deadline_epoch']) == {'state': 'deadline'}
    rows = [{'acquire': 'failed_uncertain'}, {}, {}, {}]
    assert select_next(PREPARATION, rows, NOW) == {'state': 'stopped', 'reason': 'common_or_uncertain_failure'}
