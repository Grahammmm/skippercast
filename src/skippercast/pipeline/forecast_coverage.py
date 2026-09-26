"""Audit the forecast hours a regional rating actually needs.

This is a coverage check, not a weather or fishing score. It uses the same
Pacific 7 a.m.–1 p.m. sample window as the public morning cards and never
counts a missing model value as calm weather.
"""
from datetime import datetime, timedelta, timezone
import math
from zoneinfo import ZoneInfo


WIND_MODELS = ('gfs_global', 'ecmwf_ifs025')
WAVE_MODELS = ('ncep_gfswave016', 'ecmwf_wam')


def _sample(model, point_index, epoch, field, unit, now):
    data = model.get('data') or []
    meta = model.get('meta') or {}
    if point_index >= len(data) or not isinstance(meta.get('last_run_initialisation_time'), (int, float)):
        return None
    if now.timestamp() - meta['last_run_initialisation_time'] > 36 * 3600:
        return None
    if isinstance(meta.get('data_end_time'), (int, float)) and epoch > meta['data_end_time']:
        return None
    row = data[point_index]
    hourly, units = row.get('hourly') or {}, row.get('hourly_units') or {}
    times, values = hourly.get('time'), hourly.get(field)
    if (units.get('time') != 'unixtime' or row.get('utc_offset_seconds') != 0 or
            units.get(field) != unit or not isinstance(times, list) or
            not isinstance(values, list) or len(times) != len(values)):
        return None
    try:
        index = times.index(epoch)
    except ValueError:
        return None
    if times.count(epoch) != 1:
        return None
    value = values[index]
    if field == 'wave_height':
        periods = hourly.get('wave_period')
        if (units.get('wave_period') != 's' or not isinstance(periods, list) or
                len(periods) != len(times) or not isinstance(periods[index], (int, float)) or
                not math.isfinite(periods[index]) or periods[index] <= 0):
            return None
    return value if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else None


def audit_forecast_coverage(forecast, region, now):
    """Return per-point, per-date rated-hour and independent-model coverage."""
    zone = ZoneInfo(region['timezone'])
    today = now.astimezone(zone).date()
    models = forecast.get('models') or {}
    points = []
    for index, point in enumerate(region['forecast_points']):
        days = []
        for offset in range(1, 8):
            day = today + timedelta(days=offset)
            rated = compared = 0
            for hour in range(7, 14):
                epoch = int(datetime(day.year, day.month, day.day, hour, tzinfo=zone).timestamp())
                winds = [_sample(models.get(name) or {}, index, epoch, 'wind_speed_10m', 'kn', now)
                         for name in WIND_MODELS]
                seas = [_sample(models.get(name) or {}, index, epoch, 'wave_height', 'ft', now)
                        for name in WAVE_MODELS]
                if any(value is not None for value in winds) and any(value is not None for value in seas):
                    rated += 1
                if all(value is not None for value in winds + seas):
                    compared += 1
            days.append({'date': day.isoformat(), 'rated_hours': rated, 'two_model_hours': compared,
                         'status': 'unavailable' if rated == 0 else 'limited' if rated < 7 or compared < 7 else 'complete'})
        points.append({'point_id': point['id'], 'days': days})
    all_days = [day for point in points for day in point['days']]
    return {'window': '7 a.m.–1 p.m. local, next seven dates', 'points': points,
            'summary': {'point_days': len(all_days),
                        'rated_point_days': sum(day['rated_hours'] == 7 for day in all_days),
                        'two_model_point_days': sum(day['two_model_hours'] == 7 for day in all_days),
                        'incomplete_point_days': sum(day['rated_hours'] < 7 for day in all_days),
                        'unavailable_point_days': sum(day['rated_hours'] == 0 for day in all_days)}}
