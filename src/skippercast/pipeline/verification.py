"""Prospective, station-specific forecast verification, without fitted corrections.

Version-one archive rows remain readable. New metadata improves their interpretation;
it never turns a retrospectively downloaded forecast into a prospective prediction.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
import math

BUCKETS = ((0, 12), (12, 24), (24, 48), (48, 72), (72, 168))
UNITS = {'wave_height': 'ft', 'wind_speed_10m': 'kn'}
MATCH_SECONDS = 1800
MAX_GRID_DISTANCE_KM = 30
MIN_VALID_TIMES, MIN_DAYS, MIN_RUNS = 30, 7, 3
MIN_COVERAGE = 0.7
ACCEPTED_QA = {'provisional_automated', 'passed', 'legacy_unrecorded'}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def coordinates(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2 and
            all(number(v) for v in value) and -90 <= value[0] <= 90 and -180 <= value[1] <= 180)


def distance_km(a, b):
    if not coordinates(a) or not coordinates(b):
        return None
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2 - lat1, math.radians(b[1] - a[1])
    chord = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, chord))))


def lead_bucket(lead):
    return next(((a, b) for a, b in BUCKETS if a <= lead < b or (b == 168 and lead == 168)), None)


def forecast_records(model, data, received_at, stations):
    meta = data['meta']
    cycle = meta.get('last_run_initialisation_time')
    if not number(received_at) or not number(cycle) or cycle > received_at:
        raise ValueError('Invalid forecast initialization')
    available = meta.get('last_run_availability_time')
    if available is not None and (not number(available) or available < cycle or available > received_at):
        raise ValueError('Forecast availability is inconsistent with acquisition')
    # The provider documents eventual consistency across API servers. Do not
    # attribute a just-changing response to the new run during that interval.
    if number(available) and received_at < available + 600:
        raise ValueError('Forecast is inside the provider ten-minute update settling window')
    records = []
    variable = 'wave_height' if 'wave' in model or 'wam' in model else 'wind_speed_10m'
    for station, point in zip(stations, data['points'], strict=True):
        grid = [point.get('latitude'), point.get('longitude')]
        if not coordinates(grid) or variable not in station['variables']:
            continue
        unit = UNITS[variable]
        if point['hourly_units'].get(variable) != unit:
            raise ValueError('Verification unit mismatch')
        requested = [station.get('latitude'), station.get('longitude')]
        station_coordinates = requested if coordinates(requested) else None
        times = point['hourly']['time']
        if len(times) != len(set(times)):
            raise ValueError('Duplicate verification forecast valid time')
        for epoch, value in zip(times, point['hourly'][variable], strict=True):
            if not number(epoch) or epoch <= received_at or not number(value) or value < 0:
                continue
            if epoch > meta.get('data_end_time', epoch) or not lead_bucket((epoch - cycle) / 3600):
                continue
            ident = f'{model}:{int(cycle)}:{station["id"]}:{epoch}:{variable}'
            records.append({'id': ident, 'model': model, 'cycle': cycle, 'acquired_at': received_at,
                            'station': station['id'], 'time': epoch, 'variable': variable,
                            'value': value, 'unit': unit, 'grid': grid,
                            'station_coordinates': station_coordinates,
                            'grid_distance_km': distance_km(grid, station_coordinates),
                            'max_grid_distance_km': station.get('max_grid_distance_km', MAX_GRID_DISTANCE_KM),
                            'model_available_at': available,
                            'model_modified_at': meta.get('last_run_modification_time'),
                            'native_step_seconds': meta.get('temporal_resolution_seconds'),
                            'run_attribution': 'provider_metadata',
                            'anemometer_height_m': station.get('anemometer_height_m')})
    return records


def merge_records(existing, new, now, retention_days=30):
    result = {r['id']: r for r in existing if number(r.get('time')) and r['time'] >= now - retention_days * 86400}
    for row in new:
        if number(row.get('time')) and row['time'] >= now - retention_days * 86400:
            result.setdefault(row['id'], row)
    return sorted(result.values(), key=lambda r: (r['time'], r['id']))


def observation_records(station, rows, received_at, source_url):
    """Normalize NDBC realtime measurements; never label provisional data final QC."""
    result = []
    for row in rows:
        epoch = datetime.fromisoformat(row['time'].replace('Z', '+00:00')).timestamp()
        for variable, key, factor in [('wave_height', 'WVHT', 3.28084), ('wind_speed_10m', 'WSPD', 1.94384449)]:
            if variable == 'wind_speed_10m' and station.get('wind_verification') == 'ndbc-derived-10m':
                continue
            value = row.get(key)
            if variable not in station['variables'] or not number(value) or value < 0:
                continue
            qa = 'provisional_automated'
            if variable == 'wind_speed_10m' and number(row.get('GST')) and row['GST'] < value:
                qa = 'inconsistent_gust'
            result.append({'id': f'{station["id"]}:{epoch}:{variable}', 'station': station['id'],
                           'time': epoch, 'variable': variable, 'value': value * factor, 'unit': UNITS[variable],
                           'received_at': received_at, 'source_url': source_url, 'qa': qa,
                           'station_coordinates': [station.get('latitude'), station.get('longitude')],
                           'measurement_height_m': station.get('anemometer_height_m') if variable == 'wind_speed_10m' else None,
                           'height_adjustment': 'none', 'reference_type': 'measured'})
    return result


def derived_wind_data(body, station):
    """NDBC WSPD10 is a provider-derived estimate, not a direct 10 m sensor."""
    lines = body.strip().splitlines()
    if len(lines) < 3 or not lines[0].startswith('#YY'):
        raise ValueError('NDBC derived wind header missing')
    keys, units = lines[0].lstrip('#').split(), lines[1].lstrip('#').split()
    if len(keys) != len(units) or 'WSPD10' not in keys or dict(zip(keys, units))['WSPD10'] != 'm/s':
        raise ValueError('NDBC derived wind fields or units changed')
    observations = []
    for line in lines[2:6502]:
        values = line.split()
        if len(values) != len(keys):
            raise ValueError('Malformed NDBC derived wind row')
        row = dict(zip(keys, values))
        epoch = datetime(*map(int, values[:5]), tzinfo=timezone.utc).timestamp()
        raw = row['WSPD10']
        if raw in {'MM', '999', '999.0', '9999', '9999.0'}:
            continue
        value = float(raw)
        if not number(value) or not 0 <= value <= 67:
            continue
        observations.append({'time': epoch, 'value': value * 1.94384449, 'native_value': value})
    if not observations:
        raise ValueError('No usable NDBC derived 10 m winds')
    return {'station': station, 'sample_at': datetime.fromtimestamp(max(o['time'] for o in observations), timezone.utc).isoformat().replace('+00:00', 'Z'),
            'unit': 'kn', 'native_unit': 'm/s', 'observations': observations,
            'method': 'NDBC WSPD10 estimate using the provider air-sea bulk adjustment; no SkipperCast correction',
            'reference_type': 'derived_10m', 'quality': 'provisional_automated'}


def derived_wind_records(station, data, received_at, source_url):
    if data.get('station') != station['id'] or data.get('unit') != 'kn':
        raise ValueError('NDBC derived wind station or unit mismatch')
    return [{'id': f'{station["id"]}:{o["time"]}:wind_speed_10m', 'station': station['id'],
             'time': o['time'], 'variable': 'wind_speed_10m', 'value': o['value'], 'unit': 'kn',
             'received_at': received_at, 'source_url': source_url, 'qa': 'provisional_automated',
             'station_coordinates': [station.get('latitude'), station.get('longitude')],
             'measurement_height_m': 10, 'sensor_height_m': station.get('anemometer_height_m'),
             'height_adjustment': 'NDBC WSPD10 bulk estimate', 'reference_type': 'derived_10m',
             'native_value': o['native_value'], 'native_unit': 'm/s'} for o in data['observations']]


def merge_observations(existing, new, now, retention_days=30):
    """Allow documented provider corrections, without inventing original receipt times."""
    result = {o['id']: o for o in existing if number(o.get('time')) and o['time'] >= now - retention_days * 86400}
    for row in new:
        if not number(row.get('time')) or row['time'] < now - retention_days * 86400:
            continue
        old = result.get(row['id'])
        if old and number(old.get('received_at')) and (not number(row.get('received_at')) or row['received_at'] < old['received_at']):
            continue
        value = dict(row)
        value['first_received_at'] = (old.get('first_received_at', old.get('received_at')) if old else row.get('received_at'))
        value['revision_count'] = (old.get('revision_count', 0) + int(any(old.get(k) != row.get(k) for k in ('value', 'unit'))) if old else 0)
        if old and 'previous_reference_type' in old:
            value['previous_reference_type'] = old['previous_reference_type']
        if old and old.get('reference_type', 'legacy_unrecorded') != row.get('reference_type', 'legacy_unrecorded'):
            value['previous_reference_type'] = old.get('reference_type', 'legacy_unrecorded')
        result[row['id']] = value
    return sorted(result.values(), key=lambda r: (r['time'], r['id']))


def _identity(row, forecast=False):
    keys = ('station', 'variable', 'time', 'model', 'cycle') if forecast else ('station', 'variable', 'time')
    return tuple(row.get(k) for k in keys)


def _range(values, digits=3):
    present = [v for v in values if number(v)]
    return [round(min(present), digits), round(max(present), digits)] if present else None


def _support(rows, coverage):
    times = {r['forecast']['time'] for r in rows}
    days = {datetime.fromtimestamp(t, timezone.utc).date() for t in times}
    runs = {r['forecast']['cycle'] for r in rows}
    enough = len(times) >= MIN_VALID_TIMES and len(days) >= MIN_DAYS and len(runs) >= MIN_RUNS
    quality = all(r['distance_km'] is not None and r['observation'].get('qa') in ACCEPTED_QA - {'legacy_unrecorded'} for r in rows)
    status = 'descriptive' if enough and quality and coverage >= MIN_COVERAGE else 'early sample' if not enough else 'limited comparability'
    return status, len(times), len(days), len(runs)


def verify(records, observations, now, stations=None):
    station_map = {s['id']: s for s in (stations or [])}
    diagnostics = Counter()
    # Deduplicate by the physical sample, not by a mutable provider ID. Prefer
    # the newest observation revision; forecasts retain their first acquisition.
    unique_obs = {}
    for row in observations:
        if not number(row.get('time')) or row['time'] > now:
            diagnostics['future_or_invalid_observations'] += 1
            continue
        key = _identity(row)
        old = unique_obs.get(key)
        if old is None or (row.get('received_at') or 0) > (old.get('received_at') or 0):
            unique_obs[key] = row
    diagnostics['duplicate_observations'] = len(observations) - len(unique_obs) - diagnostics['future_or_invalid_observations']
    by_station = defaultdict(list)
    for row in unique_obs.values():
        value, variable = row.get('value'), row.get('variable')
        ceiling = 165 if variable == 'wave_height' else 130
        if (variable not in UNITS or row.get('unit') != UNITS[variable] or
                not number(value) or not 0 <= value <= ceiling or
                row.get('qa', 'legacy_unrecorded') not in ACCEPTED_QA or
                (number(row.get('received_at')) and row['received_at'] > now)):
            diagnostics['rejected_observations'] += 1
            continue
        by_station[(row['station'], variable)].append(row)
    unique = {}
    for row in records:
        if not all(number(row.get(k)) for k in ('time', 'cycle', 'acquired_at', 'value')):
            diagnostics['invalid_forecasts'] += 1
            continue
        key = _identity(row, True)
        if key not in unique or row['acquired_at'] < unique[key]['acquired_at']:
            unique[key] = row
    diagnostics['duplicate_forecasts'] = len(records) - len(unique) - diagnostics['invalid_forecasts']
    groups, matches, used_observations = {}, [], set()
    for f in sorted(unique.values(), key=lambda r: (r['time'], r['cycle'], r.get('model', ''))):
        if (not f['cycle'] <= f['acquired_at'] < f['time'] or f['acquired_at'] > now or f['value'] < 0 or
                f.get('variable') not in UNITS or f.get('unit') != UNITS.get(f.get('variable')) or
                (number(f.get('model_available_at')) and f['model_available_at'] > f['acquired_at'])):
            diagnostics['nonprospective_or_invalid_forecasts'] += 1
            continue
        bucket = lead_bucket((f['time'] - f['cycle']) / 3600)
        if not bucket:
            diagnostics['outside_verification_horizon'] += 1
            continue
        key = (f['station'], f['model'], f['variable'], bucket)
        group = groups.setdefault(key, {'rows': [], 'eligible': 0, 'unmatched': 0, 'future': 0,
                                        'awaiting': 0, 'spatial_excluded': 0, 'forecasts': []})
        group['forecasts'].append(f)
        if f['time'] > now:
            group['future'] += 1
            continue
        station = station_map.get(f['station'], {})
        station_coords = f.get('station_coordinates') or [station.get('latitude'), station.get('longitude')]
        distance = distance_km(f.get('grid'), station_coords)
        limit = f.get('max_grid_distance_km', station.get('max_grid_distance_km', MAX_GRID_DISTANCE_KM))
        if not number(limit) or limit <= 0 or (distance is not None and distance > limit):
            group['spatial_excluded'] += 1
            diagnostics['grid_too_distant'] += 1
            continue
        candidates = [o for o in by_station.get((f['station'], f['variable']), [])
                      if abs(o['time'] - f['time']) <= MATCH_SECONDS and o['time'] > f['acquired_at']]
        # A midpoint observation may fit two hours. Within a run, count it once.
        candidates.sort(key=lambda o: (abs(o['time'] - f['time']), o['time']))
        obs = next((o for o in candidates if (f['model'], f['cycle'], *_identity(o)) not in used_observations), None)
        if obs is None:
            if f['time'] + MATCH_SECONDS > now:
                group['awaiting'] += 1
            else:
                group['eligible'] += 1
                group['unmatched'] += 1
            continue
        used_observations.add((f['model'], f['cycle'], *_identity(obs)))
        group['eligible'] += 1
        match = {'forecast': f, 'observation': obs, 'error': f['value'] - obs['value'], 'distance_km': distance, 'bucket': bucket}
        group['rows'].append(match)
        matches.append(match)
    result = []
    for (station, model, variable, bucket), group in sorted(groups.items()):
        rows, eligible = group['rows'], group['eligible']
        errors = [r['error'] for r in rows]
        n = len(rows)
        coverage = n / eligible if eligible else None
        status, valid_times, days, runs = _support(rows, coverage or 0)
        if not n:
            status = 'awaiting observations' if group['future'] or group['awaiting'] else 'no matches'
        spatial_unknown = sum(r['distance_km'] is None for r in rows)
        quality = Counter(r['observation'].get('qa', 'legacy_unrecorded') for r in rows)
        height_match = variable != 'wind_speed_10m' or all(r['observation'].get('measurement_height_m') == 10 for r in rows)
        derived_wind = variable == 'wind_speed_10m' and any(r['observation'].get('reference_type') == 'derived_10m' for r in rows)
        observation_latest = max((o['time'] for o in by_station.get((station, variable), [])), default=None)
        forecast_latest = max((f['acquired_at'] for f in group['forecasts']), default=None)
        fresh = (observation_latest is not None and now - observation_latest <= 3 * 3600 and
                 forecast_latest is not None and now - forecast_latest <= 36 * 3600)
        ready = status == 'descriptive' and height_match and fresh
        result.append({'station': station, 'model': model, 'variable': variable, 'lead_hours': list(bucket),
                       'n': n, 'distinct_days': days, 'distinct_runs': runs, 'distinct_valid_times': valid_times,
                       'bias': round(sum(errors) / n, 3) if n else None,
                       'mae': round(sum(abs(e) for e in errors) / n, 3) if n else None,
                       'rmse': round(math.sqrt(sum(e * e for e in errors) / n), 3) if n else None,
                       'unit': UNITS[variable], 'status': status, 'eligible_forecasts': eligible,
                       'unmatched_forecasts': group['unmatched'], 'future_forecasts': group['future'],
                       'awaiting_observations': group['awaiting'], 'coverage_fraction': round(coverage, 3) if coverage is not None else None,
                       'valid_time_range': _range([r['forecast']['time'] for r in rows], 0),
                       'acquisition_lead_hours': _range([(r['forecast']['time'] - r['forecast']['acquired_at']) / 3600 for r in rows]),
                       'match_time_offset_minutes': _range([abs(r['observation']['time'] - r['forecast']['time']) / 60 for r in rows]),
                       'spatial_match': {'distance_km': _range([r['distance_km'] for r in rows]),
                                         'unknown_samples': spatial_unknown, 'excluded_forecasts': group['spatial_excluded'],
                                         'default_max_distance_km': MAX_GRID_DISTANCE_KM},
                       'observation_quality': dict(quality),
                       'collection': {'latest_observation_at': observation_latest,
                                      'observation_age_hours': round((now - observation_latest) / 3600, 2) if observation_latest is not None else None,
                                      'latest_forecast_acquired_at': forecast_latest,
                                      'forecast_age_hours': round((now - forecast_latest) / 3600, 2) if forecast_latest is not None else None,
                                      'forecast_valid_through': max(f['time'] for f in group['forecasts']),
                                      'fresh': fresh},
                       'measurement_comparison': 'NDBC-derived 10 m wind estimate' if height_match and derived_wind else 'same-height' if variable == 'wind_speed_10m' and height_match else 'unadjusted buoy-height wind' if variable == 'wind_speed_10m' else 'significant wave height',
                       'support': {'level': 'local descriptive evidence' if ready else 'limited',
                                   'usable_for_model_comparison': ready, 'calibrated_probability': False,
                                   'next_action': 'Inspect common-case comparisons; do not apply automatic corrections.' if ready else
                                   'Restore current station/model collection before using this historical comparison.' if not fresh and status == 'descriptive' else
                                   'Verify wind sensor height before comparing 10 m model skill.' if not height_match and status == 'descriptive' else
                                   'Keep collecting matched observations across at least 7 days and 30 distinct valid times; inspect missing or distant samples.'}})
    comparisons = _comparisons(matches)
    eligible = sum(g['eligible_forecasts'] for g in result)
    usable = sum(g['support']['usable_for_model_comparison'] for g in result)
    valid_keys = {(r['forecast']['station'], r['forecast']['variable'], r['forecast']['time']) for r in matches}
    latest_observation = max((r['time'] for rows in by_station.values() for r in rows), default=None)
    latest_forecast = max((r['acquired_at'] for r in unique.values() if r['acquired_at'] <= now), default=None)
    stale = (latest_forecast is not None and now - latest_forecast > 36 * 3600) or (latest_observation is not None and now - latest_observation > 3 * 3600)
    summary_status = 'stale evidence' if stale else 'descriptive evidence' if usable else 'collecting history'
    return {'method_version': 'prospective-v2', 'status': 'descriptive' if usable else 'collecting history',
            'generated_at': datetime.fromtimestamp(now, timezone.utc).isoformat().replace('+00:00', 'Z'),
            'groups': result, 'comparisons': comparisons, 'archived_forecasts': len(unique), 'matched_samples': len(matches),
            'diagnostics': dict(diagnostics),
            'summary': {'status': summary_status, 'headline': f'{len(valid_keys)} station/variable valid times checked; {usable} groups have local descriptive support',
                        'usable_groups': usable, 'matched_valid_times': len(valid_keys), 'eligible_forecasts': eligible,
                        'coverage_fraction': round(len(matches) / eligible, 3) if eligible else None,
                        'latest_forecast_acquired_at': latest_forecast, 'latest_observation_at': latest_observation,
                        'observation_age_hours': round((now - latest_observation) / 3600, 2) if latest_observation is not None else None,
                        'archive_valid_time_range': _range([r['time'] for r in unique.values()], 0),
                        'calibrated_probability': False,
                        'next_action': 'Restore current collection; historical errors cannot verify current conditions.' if stale else
                        'Use station, lead and common-case comparisons; errors are not a safety clearance.' if usable else
                        'Collect more days before choosing a locally superior model or adjusting ratings.'},
            'policy': {'match_tolerance_minutes': 30, 'default_max_grid_distance_km': MAX_GRID_DISTANCE_KM,
                       'minimum_distinct_valid_times': MIN_VALID_TIMES, 'minimum_days': MIN_DAYS,
                       'minimum_runs': MIN_RUNS, 'minimum_coverage_fraction': MIN_COVERAGE,
                       'lead_hours': [list(b) for b in BUCKETS], 'retention_days': 30},
            'limitations': 'Descriptive errors, not calibrated forecast probabilities or catch predictions. No retrospective forecast reconstruction or automatic bias correction. Samples share weather systems and are not independent. NDBC realtime observations and derived 10 m wind estimates are provisional. Derived winds have adjustment and source rounding uncertainty; unadjusted buoy-height winds cannot establish 10 m wind skill. Grid proximity does not prove matching exposure; islands, coastal shelter and bathymetry matter. Provider run metadata is not independent per-value run certification.'}


def _comparisons(matches):
    """Use exactly the same station, initialization, valid hour and observation."""
    by_case = defaultdict(dict)
    for row in matches:
        f, obs = row['forecast'], row['observation']
        if row['distance_km'] is None or obs.get('qa') not in ACCEPTED_QA - {'legacy_unrecorded'}:
            continue
        if f['variable'] == 'wind_speed_10m' and obs.get('measurement_height_m') != 10:
            continue
        key = (f['station'], f['variable'], row['bucket'], f['cycle'], f['time'], obs['time'])
        by_case[key][f['model']] = row
    groups = defaultdict(list)
    available = Counter()
    for row in matches:
        f = row['forecast']
        available[(f['station'], f['variable'], row['bucket'], f['model'])] += 1
    for case, models in by_case.items():
        for a, b in combinations(sorted(models), 2):
            groups[(case[0], case[1], case[2], a, b)].append((case, models[a], models[b]))
    result = []
    for (station, variable, bucket, a, b), rows in sorted(groups.items()):
        status, times, days, runs = _support([r[1] for r in rows], 1)
        fraction_a = len(rows) / available[(station, variable, bucket, a)]
        fraction_b = len(rows) / available[(station, variable, bucket, b)]
        if status == 'descriptive' and min(fraction_a, fraction_b) < MIN_COVERAGE:
            status = 'limited common-case coverage'
        mae_a = sum(abs(r[1]['error']) for r in rows) / len(rows)
        mae_b = sum(abs(r[2]['error']) for r in rows) / len(rows)
        result.append({'station': station, 'variable': variable, 'lead_hours': list(bucket),
                       'model_a': a, 'model_b': b, 'n': len(rows), 'distinct_valid_times': times,
                       'distinct_days': days, 'distinct_runs': runs, 'status': status,
                       'mae_a': round(mae_a, 3), 'mae_b': round(mae_b, 3),
                       'mae_difference_a_minus_b': round(mae_a - mae_b, 3), 'unit': UNITS[variable],
                       'common_case_fraction_a': round(fraction_a, 3), 'common_case_fraction_b': round(fraction_b, 3),
                       'lower_error_model': (a if mae_a < mae_b else b if mae_b < mae_a else None) if status == 'descriptive' else None,
                       'interpretation': 'Same-case empirical difference only; not statistical significance or a forecast probability.'})
    return result
