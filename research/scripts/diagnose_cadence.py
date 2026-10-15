"""Private offline AIS scheduling report, introduced 2026-10-15.

Dated against workflow source d6575df4b589b743bbab0a0c2a3c9e33c6bed962.
Reuses the bounded coordination diagnostic and its seven synthetic tests.
No API calls, environment credentials, issue posts, services or scheduler writes.
Product code/workflows must not import this research tool.

Inputs are local JSON exports, never raw AIS positions:
- runs: Actions run objects (id, event, status, conclusion, created_at).
- jobs: [{run_id, jobs: [{started_at, completed_at, conclusion}]}].
- publications: optional [{run_id, run_kind: "normal", published_at}]. These
  are explicit successful publication observations supplied by the caller,
  correlated to successful associated job intervals. Caller observations are not
  authenticated publication provenance; job success is not a publication proxy.
  Historical/backfill/validation/label runs are excluded. Manual normal
  publication can show ordinary freshness but cannot fill natural-run gaps.

Exhaustive window coverage and export/publication provenance cannot be established
from these local inputs. Their assessment remains unknown, including when a
subset meets the selected numeric test. No trigger-slot attribution or lost
trigger count is inferred. Freshness bounds are caller-selected test values;
40 minutes is proposed for testing only, never a default operational policy.
The CLI requires a create-only output path (0600), prints no report publicly,
and exits 2 after writing a report: this input contract cannot establish
coverage/provenance and therefore has no success/acceptance exit path. Numeric
subset results are observations only, never operational acceptance.

Example (40 is a proposed test value, not an approved operating threshold):
python -m research.scripts.diagnose_cadence --runs /private/runs.json \
  --jobs /private/jobs.json --publications /private/publications.json \
  --observed-at 2026-10-15T00:35:00Z --freshness-bound-minutes 40 \
  --output /private/new-report.json

No output path is inferred from GITHUB_STEP_SUMMARY or another environment value.
"""
import json
from datetime import datetime
from statistics import median
from pathlib import Path

def stamp(value):
    at = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if at.tzinfo is None:
        raise ValueError('timestamp must include timezone')
    return at

def analyse(runs, job_rows):
    jobs = {row['run_id']: row['jobs'] for row in job_rows}
    selected = sorted((r for r in runs if r['event'] == 'schedule'), key=lambda r: stamp(r['created_at']))
    gaps = [(stamp(b['created_at']) - stamp(a['created_at'])).total_seconds()/60 for a,b in zip(selected, selected[1:])]
    delays, durations, skipped, pending, unknown = [], [], 0, 0, 0
    for run in selected:
        records = jobs.get(run['id'], [])
        if not records:
            pending += run['status'] != 'completed'
            unknown += run['status'] == 'completed'
        for job in records:
            skipped += job.get('conclusion') == 'skipped'
            if job.get('started_at'):
                delays.append((stamp(job['started_at']) - stamp(run['created_at'])).total_seconds())
            if job.get('started_at') and job.get('completed_at'):
                durations.append((stamp(job['completed_at']) - stamp(job['started_at'])).total_seconds())
    return {'scheduled_runs':len(selected),'median_creation_gap_minutes':median(gaps) if gaps else None,
            'max_creation_gap_minutes':max(gaps) if gaps else None,'max_job_start_delay_seconds':max(delays) if delays else None,
            'max_job_duration_seconds':max(durations) if durations else None,'skipped_jobs':skipped,
            'created_pending_without_jobs':pending,'completed_runs_without_job_evidence':unknown,
            'trigger_delivery_cause':'unknown: run metadata cannot distinguish late delivery from lost events'}



PROPOSED_TEST_BOUND_MINUTES = 40
UNKNOWN_CAUSE = 'unknown: run metadata cannot distinguish late delivery from lost events'


def _unknown(reason):
    return {'status': 'unknown', 'reason': reason}


def _validate_runs(runs):
    if not isinstance(runs, list):
        raise ValueError('runs must be an array')
    ids = set()
    for run in runs:
        if not isinstance(run, dict) or type(run.get('id')) is not int or run['id'] in ids:
            raise ValueError('runs need unique integer ids')
        ids.add(run['id'])
        if not isinstance(run.get('event'), str) or not isinstance(run.get('status'), str):
            raise ValueError('run event/status missing')
        stamp(run['created_at'])


def _execution(selected, job_rows, observed):
    if not selected:
        return _unknown('no natural run evidence')
    if not isinstance(job_rows, list):
        return _unknown('job evidence missing or malformed')
    indexed = {}
    try:
        for row in job_rows:
            if not isinstance(row, dict) or type(row.get('run_id')) is not int or row['run_id'] in indexed:
                raise ValueError('ambiguous job evidence')
            if not isinstance(row.get('jobs'), list):
                raise ValueError('malformed jobs')
            indexed[row['run_id']] = row['jobs']
        missing, skipped, unsuccessful, incomplete, failed_runs = 0, 0, 0, 0, 0
        delays, durations = [], []
        for run in selected:
            records = indexed.get(run['id'], [])
            incomplete += run['status'] != 'completed' or run.get('conclusion') is None
            failed_runs += run['status'] == 'completed' and run.get('conclusion') not in (None, 'success')
            missing += not bool(records)
            for job in records:
                conclusion = job.get('conclusion')
                if conclusion is not None and conclusion not in ('success', 'failure', 'cancelled', 'timed_out', 'action_required', 'skipped', 'neutral', 'stale', 'startup_failure'):
                    raise ValueError('unknown job conclusion')
                skipped += conclusion == 'skipped'
                unsuccessful += conclusion is not None and conclusion not in ('success', 'skipped')
                if not job.get('started_at') or not job.get('completed_at') or not conclusion:
                    incomplete += 1
                    continue
                start, end, created = stamp(job['started_at']), stamp(job['completed_at']), stamp(run['created_at'])
                if start < created or end < start or (observed is not None and end > observed):
                    raise ValueError('invalid job chronology')
                delays.append((start - created).total_seconds())
                durations.append((end - start).total_seconds())
        return {'status': 'unknown' if missing or incomplete else 'attention' if skipped or unsuccessful or failed_runs else 'observed',
                'missing_run_job_records': missing, 'incomplete_jobs': incomplete,
                'skipped_jobs': skipped, 'unsuccessful_jobs': unsuccessful, 'unsuccessful_runs': failed_runs,
                'max_job_start_delay_seconds': max(delays) if delays else None,
                'max_job_duration_seconds': max(durations) if durations else None,
                'scope': 'created natural runs only; not nominal trigger delivery delay'}
    except (KeyError, TypeError, ValueError, AttributeError):
        return _unknown('job evidence malformed, ambiguous or chronologically invalid')


def _publication_job_interval(run, job_rows, published, observed):
    """Temporal sanity only; matching an interval does not authenticate a publisher."""
    if not isinstance(job_rows, list):
        raise ValueError('associated job evidence missing')
    associated = [row for row in job_rows if isinstance(row, dict) and type(row.get('run_id')) is int
                  and row['run_id'] == run['id']]
    if len(associated) != 1 or not isinstance(associated[0].get('jobs'), list) or not associated[0]['jobs']:
        raise ValueError('associated job evidence missing or ambiguous')
    intervals = []
    for job in associated[0]['jobs']:
        start, end = stamp(job['started_at']), stamp(job['completed_at'])
        if start < stamp(run['created_at']) or end < start or (observed is not None and end > observed):
            raise ValueError('invalid associated job chronology')
        if job.get('conclusion') == 'success':
            intervals.append((start, end))
    if not any(start <= published <= end for start, end in intervals):
        raise ValueError('publication outside successful associated job intervals')


def _freshness(runs, job_rows, publications, observed, bound):
    unknown = lambda reason: {'ordinary': _unknown(reason), 'natural': _unknown(reason)}
    if not isinstance(publications, list):
        return unknown('explicit publication evidence missing')
    indexed = {run['id']: run for run in runs}
    ordinary, natural, seen = [], [], set()
    try:
        for row in publications:
            if not isinstance(row, dict) or type(row.get('run_id')) is not int or row.get('run_kind') not in ('normal', 'window', 'backfill', 'validation', 'label-import'):
                raise ValueError('publication kind missing')
            if row['run_kind'] != 'normal':
                continue
            run = indexed[row['run_id']]
            if run['event'] not in ('schedule', 'workflow_dispatch'):
                raise ValueError('unsupported publication event')
            if run['status'] != 'completed' or run.get('conclusion') != 'success':
                raise ValueError('successful run evidence missing')
            published = stamp(row['published_at'])
            if published < stamp(run['created_at']) or (observed is not None and published > observed):
                raise ValueError('invalid publication chronology')
            _publication_job_interval(run, job_rows, published, observed)
            if run['id'] in seen:
                raise ValueError('ambiguous publication observations')
            seen.add(run['id'])
            ordinary.append((published, run['event']))
            if run['event'] == 'schedule':
                natural.append((published, run['event']))
        missing = sum(run['event'] == 'schedule' and run['status'] == 'completed'
                      and run.get('conclusion') == 'success' and run['id'] not in seen for run in runs)
        def assess(records):
            if not records:
                return _unknown('no matching ordinary publication observation')
            latest, trigger = max(records)
            age = (observed - latest).total_seconds() / 60 if observed is not None else None
            gaps = [(b[0] - a[0]).total_seconds()/60 for a,b in zip(sorted(records), sorted(records)[1:])]
            status = ('unknown' if observed is None or bound is None or missing else
                      'outside_test_bound' if age > bound or any(gap > bound for gap in gaps) else 'within_test_bound')
            return {'status': 'unknown', 'observed_subset_test_result': status,
                    'latest_published_at': latest.isoformat(), 'latest_trigger': trigger,
                    'age_minutes': age, 'max_observed_publication_gap_minutes': max(gaps) if gaps else None,
                    'missing_natural_publication_records': missing,
                    'reason': 'observed subset only; exhaustive window coverage and publication provenance not established'}
        return {'ordinary': assess(ordinary), 'natural': assess(natural)}
    except (KeyError, TypeError, ValueError, AttributeError):
        return unknown('publication evidence malformed, uncorrelated or chronologically invalid')


def report(runs, job_rows, publications=None, *, observed_at=None, freshness_bound_minutes=None):
    """Three independent evidence sections; unknown data cannot become a health pass."""
    import math
    bound = freshness_bound_minutes
    if bound is not None and (type(bound) not in (int, float) or not math.isfinite(bound) or bound <= 0):
        raise ValueError('freshness test bound must be a finite positive number')
    result = {'schema_version': 1,
              'coverage': {'status': 'unknown', 'scope': 'supplied records only',
                           'reason': 'exhaustive window and export provenance not established'},
              'publication_provenance': _unknown('caller observations and input hashes do not authenticate publication'),
              'operational_acceptance': 'not_evaluated', 'trigger_delivery_cause': UNKNOWN_CAUSE,
              'freshness_bound': {'minutes': bound, 'proposed_test_minutes': PROPOSED_TEST_BOUND_MINUTES,
                                  'policy': 'test value only; no owner-approved operational policy inferred'}}
    observed = stamp(observed_at) if observed_at is not None else None
    result['observed_at'] = observed.isoformat() if observed is not None else None
    try:
        _validate_runs(runs)
        selected = sorted((run for run in runs if run['event'] == 'schedule'), key=lambda run: stamp(run['created_at']))
        if observed is not None and any(stamp(run['created_at']) > observed for run in runs):
            raise ValueError('future run')
    except (KeyError, TypeError, ValueError, AttributeError):
        result.update(natural_creation=_unknown('run evidence missing, malformed or chronologically invalid'),
                      execution=_unknown('run evidence unavailable'),
                      publication_freshness={'ordinary': _unknown('run evidence unavailable'),
                                             'natural': _unknown('run evidence unavailable')})
        return result
    # Reuse the existing decision logic without letting missing job records erase
    # creation evidence. Execution is assessed independently below.
    metrics = analyse(runs, [])
    result['natural_creation'] = {
        'status': 'observed' if len(selected) >= 2 else 'unknown',
        'scheduled_runs': len(selected),
        'median_creation_gap_minutes': metrics['median_creation_gap_minutes'],
        'max_creation_gap_minutes': metrics['max_creation_gap_minutes'],
        'latest_creation_age_minutes': ((observed - stamp(selected[-1]['created_at'])).total_seconds()/60
                                        if observed is not None and selected else None),
        'scope': 'observed creation records; not attributed nominal slots or a lost-trigger count'}
    result['execution'] = _execution(selected, job_rows, observed)
    result['publication_freshness'] = _freshness(runs, job_rows, publications, observed, bound)
    return result


def main(argv=None):
    """Create one local private report; never write summaries/issues or overwrite a file."""
    import argparse
    import hashlib
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', required=True, type=Path)
    parser.add_argument('--jobs', required=True, type=Path)
    parser.add_argument('--publications', type=Path)
    parser.add_argument('--observed-at', required=True)
    parser.add_argument('--freshness-bound-minutes', type=float)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    values, hashes, errors = {}, {}, []
    for label in ('runs', 'jobs', 'publications'):
        path = getattr(args, label)
        try:
            raw = path.read_bytes() if path is not None else None
            values[label] = json.loads(raw) if raw is not None else None
            hashes[label] = hashlib.sha256(raw).hexdigest() if raw is not None else None
        except (OSError, ValueError):
            values[label] = None
            hashes[label] = None
            errors.append(label)
    try:
        result = report(values['runs'], values['jobs'], values['publications'], observed_at=args.observed_at,
                        freshness_bound_minutes=args.freshness_bound_minutes)
    except (TypeError, ValueError, AttributeError):
        parser.error('invalid observation time or freshness test bound')
    result['input_sha256'] = hashes
    result['unreadable_or_invalid_inputs'] = errors
    # O_EXCL refuses existing files and symlinks, including dangling symlinks.
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write('\n')
    # This local-export contract establishes neither exhaustive coverage nor
    # authenticated provenance. Do not expose a success exit merely because
    # recent points in an unqualified subset meet the proposed test value.
    return 2


if __name__ == '__main__':
    import sys
    sys.exit(main())
