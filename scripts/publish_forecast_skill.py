#!/usr/bin/env python3
"""Publish dist/data/forecast-skill.json: how often each forecast was within a stated tolerance of the buoy.

Reads each active port's verification archive (the regional tree the live-conditions job publishes), matches
forecasts to observations with the existing pipeline matcher (skippercast.pipeline.verification.verify; no second
matching rule), and counts a forecast as right when it is within the tolerance below. Wind and wave height only:
swell period and water temperature are not verified anywhere, so they are not scored.

    python3 scripts/publish_forecast_skill.py --regions-dir var/live-published/regions
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from skippercast.pipeline import verification as V  # noqa: E402
from skippercast.pipeline.verification_archive import load_archive  # noqa: E402

WIND_KN = 5               # wind: within 5 kn of the verifying observation
WAVE_FT, WAVE_BREAK_FT, WAVE_FRACTION = 1, 3, 0.25   # waves: within 1 ft at or below 3 ft, within 25% above
WINDOW_DAYS = (7, 30)     # rolling windows ending at generated_at
LEAD_OF_BUCKET = {(0, 12): 24, (12, 24): 24, (24, 48): 48, (48, 72): 72}   # the pipeline's own lead buckets
TOLERANCE = {'wind_speed_10m': f'within {WIND_KN} kn',
             'wave_height': f'within {WAVE_FT} ft at {WAVE_BREAK_FT} ft or less, within {round(WAVE_FRACTION * 100)}% above {WAVE_BREAK_FT} ft'}
EPSILON = 1e-9


def is_hit(variable, forecast, observed):
    """True when the forecast is within the stated tolerance of the observation (the limit itself counts)."""
    error = abs(forecast - observed)
    if variable == 'wind_speed_10m':
        return error <= WIND_KN + EPSILON
    return error <= (WAVE_FT if observed <= WAVE_BREAK_FT else WAVE_FRACTION * observed) + EPSILON


def matched_pairs(forecasts, observations, now, stations):
    """The pipeline's own forecast/observation matches, captured from verify() rather than re-derived."""
    captured, original = [], V._comparisons
    with mock.patch.object(V, '_comparisons', lambda matches: (captured.extend(matches), original(matches))[1]):
        V.verify(forecasts, observations, now, stations)
    return captured


def score(pairs, now, window):
    """n, within and the support triple for the pairs whose valid time falls in the rolling window."""
    rows = [p for p in pairs if now - window * 86400 < p['forecast']['time'] <= now]
    times = {p['forecast']['time'] for p in rows}
    days = {datetime.fromtimestamp(t, timezone.utc).date() for t in times}
    runs = {p['forecast']['cycle'] for p in rows}
    # The pipeline's own minimum (verification.py MIN_VALID_TIMES, MIN_DAYS, MIN_RUNS, gated in _support).
    enough = len(times) >= V.MIN_VALID_TIMES and len(days) >= V.MIN_DAYS and len(runs) >= V.MIN_RUNS
    hits = sum(is_hit(p['forecast']['variable'], p['forecast']['value'], p['observation']['value']) for p in rows)
    return {'n': len(rows), 'within': hits if enough else None, 'enough': enough,
            'valid_times': len(times), 'days': len(days), 'runs': len(runs)}


def port_scores(port, region, archive, now):
    stations = region['intelligence']['verification_stations']
    by_key = defaultdict(list)
    for pair in matched_pairs(archive['forecasts'], archive['observations'], now, stations):
        lead = LEAD_OF_BUCKET.get(tuple(pair['bucket']))
        if lead:
            by_key[(pair['forecast']['station'], pair['forecast']['variable'], lead)].append(pair)
    rows = []
    for station in stations:
        for variable in TOLERANCE:
            if variable not in station.get('variables', []):
                continue
            for lead in sorted(set(LEAD_OF_BUCKET.values())):
                for window in WINDOW_DAYS:
                    rows.append({'port': port, 'station': station['id'], 'variable': variable, 'lead_hours': lead,
                                 'window_days': window, 'tolerance': TOLERANCE[variable],
                                 **score(by_key[(station['id'], variable, lead)], now, window)})
    return rows


def build(index, regions_dir, now, statuses=('active',)):
    ports, scores = [], []
    for entry in index['regions']:
        if entry.get('status') not in statuses:
            continue
        region = json.loads((ROOT / 'regions' / entry['id'] / 'region.json').read_text())
        archive = load_archive(Path(regions_dir) / entry['id'], entry['id'])
        stations = region['intelligence']['verification_stations']
        ports.append({'id': entry['id'], 'name': entry['name'], 'stations': [{'id': s['id'], 'name': s.get('name', s['id'])} for s in stations]})
        scores += port_scores(entry['id'], region, archive, now)
    return {'schema_version': 1, 'generated_at': datetime.fromtimestamp(now, timezone.utc).isoformat().replace('+00:00', 'Z'),
            'minimum': {'valid_times': V.MIN_VALID_TIMES, 'days': V.MIN_DAYS, 'runs': V.MIN_RUNS},
            'windows_days': list(WINDOW_DAYS), 'ports': ports, 'scores': scores}


def main(argv=None):
    parser = argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0])
    parser.add_argument('--regions-dir', default=str(ROOT / 'var' / 'live-published' / 'regions'),
                        help='published regional tree holding <region>/verification-state.json')
    parser.add_argument('--index', default=str(ROOT / 'dist' / 'regions' / 'index.json'))
    parser.add_argument('--out', default=str(ROOT / 'dist' / 'data' / 'forecast-skill.json'))
    parser.add_argument('--now', type=float, help='epoch seconds; default the current time')
    parser.add_argument('--statuses', default='active', help='comma-separated region statuses counted as ports')
    args = parser.parse_args(argv)
    now = args.now if args.now is not None else datetime.now(timezone.utc).timestamp()
    result = build(json.loads(Path(args.index).read_text()), args.regions_dir, now, tuple(args.statuses.split(',')))
    Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(f"{args.out}: {len(result['ports'])} port(s), {len(result['scores'])} score row(s), "
          f"{sum(r['enough'] for r in result['scores'])} with enough data")


if __name__ == '__main__':
    main()
