"""F10-13: forecast candidate evaluation must not scale with retained history."""
import math
from unittest.mock import patch

from skippercast.pipeline import verification

DAY = 86400
VALID = 30 * DAY


def forecast(valid, cycle=VALID - 21600, **fields):
    return {'station': 'synthetic', 'variable': 'wave_height', 'unit': 'ft',
            'model': 'synthetic-model', 'time': valid, 'cycle': cycle,
            'acquired_at': cycle, 'value': 10, **fields}


def observation(time, value=2, **fields):
    return {'station': 'synthetic', 'variable': 'wave_height', 'unit': 'ft',
            'time': time, 'received_at': time + 1, 'value': value, 'qa': 'passed', **fields}


def replay(history_days):
    left, right = VALID - 1800, VALID + 1800
    forecasts = [forecast(VALID + 3600), forecast(VALID + 3599), forecast(VALID),
                 forecast(VALID, VALID - 7200, acquired_at=left)]
    nearby = [observation(right, 7), observation(left, 9), observation(VALID - 1801),
              observation(left, 3, received_at=left + 2), observation(VALID, qa='suspect'),
              observation(VALID, station='other-station'),
              observation(VALID, variable='wind_speed_10m', unit='kn'),
              observation(VALID + DAY)]
    history = [observation(time) for time in range(VALID - 3600, VALID - history_days * DAY, -600)]
    # Count absolute offsets scored by the real matcher and report, not the
    # binary-search probes. Rolling back to the full scan counts the entire tail.
    with (patch.object(verification, 'abs', wraps=abs, create=True) as offsets,
          patch.object(verification, '_comparisons', wraps=verification._comparisons) as comparisons):
        report = verification.verify(forecasts, nearby + history, VALID + 7200)
    matches = comparisons.call_args.args[0]
    return report, matches, offsets.call_count


def test_more_history_does_not_increase_candidate_scoring():
    short_report, short_matches, short_work = replay(1)
    report, matches, work = replay(30)
    assert (report, matches) == (short_report, short_matches)
    assert [(m['forecast']['time'], m['observation']['time'], m['observation']['value'])
            for m in matches] == [(VALID, VALID - 1800, 3), (VALID, VALID + 1800, 7),
                                   (VALID + 3599, VALID + 1800, 7)]
    assert report['groups'][0]['unmatched_forecasts'] == 1
    assert report['diagnostics'] == {'future_or_invalid_observations': 1, 'duplicate_observations': 1,
                                     'rejected_observations': 1, 'duplicate_forecasts': 0}
    assert work == short_work, f'absolute offset evaluations: {short_work} (1 day), {work} (30 days)'
    assert work <= 24, f'expected only nearby samples and report offsets, got {work} evaluations'


def test_window_preserves_subtraction_at_fractional_boundary():
    # A bound computed as forecast time minus the tolerance would drop this
    # sample even though the original offset rounds to exactly -1800 seconds.
    valid = 1800.5
    sample = math.nextafter(0.5, 0)
    report = verification.verify([forecast(valid, cycle=0)], [observation(sample)], 7200)
    assert report['matched_samples'] == 1
    assert report['groups'][0]['match_time_offset_minutes'] == [30, 30]
