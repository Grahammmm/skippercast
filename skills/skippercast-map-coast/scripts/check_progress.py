"""Offline effort decisions for an existing private mapping checkpoint.

No source qualification, scientific approval, scheduling or state mutation.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path


DEFAULT_LIMITS = {
    'accounted_tokens': 500_000,
    'finalization_tokens': 50_000,
    'active_minutes': 45,
    'finalization_minutes': 10,
    'candidate_tokens': 75_000,
    'repair_tokens': 100_000,
    'stage_minutes': 20,
    'preflight_minutes': 15,
    'stagnation_minutes': 30,
    'no_public_batches': 2,
}
GATES = {'native_pipeline', 'rights_path', 'screen_path', 'geometry_contract',
         'publication_contract', 'resources'}
PHASES = {'preflight', 'qualification', 'repair', 'waiting', 'finalize'}
OUTCOMES = {'published_delta', 'private_proof', 'blocked', 'no_delta',
            'pipeline_fix', 'maintenance'}


def number(value, name, *, optional=False):
    if optional and value is None:
        return None
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        raise ValueError(f'{name} must be a finite nonnegative number')
    return value


def decide(checkpoint, *, now=None):
    c = checkpoint['progress_control']
    if not c.get('run_id') or not c.get('batch_id'):
        raise ValueError('Stable run_id and batch_id are required')
    phase = c.get('phase')
    purpose = c.get('purpose')
    if phase not in PHASES or purpose not in {'publication', 'preparation'}:
        raise ValueError('Unknown phase or purpose')
    limits = dict(DEFAULT_LIMITS)
    overrides = c.get('limits', {})
    if set(overrides) - set(limits):
        raise ValueError('Unknown operating limit')
    limits.update(overrides)
    if any(value > DEFAULT_LIMITS[key] for key, value in overrides.items()):
        if not c.get('owner_limit_override'):
            raise ValueError('Increasing the run allowance requires a retained owner instruction')
    for key, value in limits.items():
        number(value, key)
        if value <= 0:
            raise ValueError('Operating limits must be positive')
    if (limits['finalization_tokens'] >= limits['accounted_tokens']
            or limits['finalization_minutes'] >= limits['active_minutes']):
        raise ValueError('Finalization reserve must fit inside the run ceiling')
    active = number(c.get('active_minutes'), 'active_minutes')
    stage = number(c.get('stage_active_minutes'), 'stage_active_minutes')
    stagnant = number(c.get('active_minutes_since_public_delta'),
                      'active_minutes_since_public_delta')
    if stage > active or stagnant > active:
        raise ValueError('Stage and stagnation time cannot exceed total active time')
    accounting = c.get('accounting', {})
    start = number(accounting.get('start'), 'accounting.start', optional=True)
    current = number(accounting.get('current'), 'accounting.current', optional=True)
    if (start is None) != (current is None):
        raise ValueError('Both accounting counters must be measured or unavailable')
    spent = None
    if start is not None:
        if not accounting.get('scope') or current < start:
            raise ValueError('Accounting requires a scope and a monotonic counter')
        spent = current - start
    candidate = number(c.get('candidate_tokens'), 'candidate_tokens', optional=True)
    repair_spent = number(c.get('repair_tokens'), 'repair_tokens', optional=True)
    if spent is not None and any(value is not None and value > spent
                                 for value in (candidate, repair_spent)):
        raise ValueError('Same-scope stage token totals cannot exceed measured run spend')
    pending = c.get('qualified_handoffs_waiting', [])
    if (not isinstance(pending, list) or any(not isinstance(x, str) or not x for x in pending)
            or len(pending) != len(set(pending))):
        raise ValueError('Waiting handoffs must be unique nonempty existing job IDs')
    no_public = 0
    preparation_completed = 0
    for event in c.get('outcomes', []):
        kind = event.get('kind')
        if kind not in OUTCOMES:
            raise ValueError('Unknown completed outcome')
        if kind == 'published_delta':
            added = number(event.get('new_outlines', 0), 'new_outlines')
            expanded = number(event.get('expanded_outlines', 0), 'expanded_outlines')
            if (not isinstance(added, int) or not isinstance(expanded, int)
                    or added + expanded <= 0 or not isinstance(event.get('readback_receipt'), str)
                    or not event['readback_receipt'].strip()):
                raise ValueError('A public reset requires positive delta and readback evidence')
            no_public = 0
        elif kind in {'private_proof', 'blocked', 'no_delta'}:
            no_public += 1
        if kind in {'private_proof', 'pipeline_fix'}:
            preparation_completed += 1
    gates = c.get('gates', {})
    if set(gates) != GATES or any(v not in {'verified', 'unknown', 'blocked'} for v in gates.values()):
        raise ValueError('All downstream readiness gates must have an explicit status')
    unready = sorted(k for k, v in gates.items() if v != 'verified')
    result = {'accounted_tokens_used': spent, 'accounting_scope': accounting.get('scope'),
              'active_minutes': active, 'completed_no_public_batches': no_public,
              'unready_gates': unready, 'scientific_or_publication_approval': False}
    if spent is None:
        result['accounting_warning'] = 'Token usage unavailable; active-time and attempt limits apply'

    def emit(action, reason):
        return dict(result, action=action, reason=reason)

    if c.get('deadline_utc') is not None:
        deadline = datetime.fromisoformat(c['deadline_utc'].replace('Z', '+00:00'))
        current_time = now or datetime.now(timezone.utc)
        if deadline.tzinfo is None or current_time.tzinfo is None:
            raise ValueError('Wall-clock deadline and current time require a timezone')
        result['deadline_utc'] = deadline.isoformat()
        if current_time >= deadline:
            return emit('STOP_ACTIVE_WORK', 'Round wall-clock deadline reached; freeze results and audit before more work')
    if active >= limits['active_minutes'] or (spent is not None and spent >= limits['accounted_tokens']):
        return emit('STOP_ACTIVE_WORK', 'Run ceiling reached; save evidence and any pending external job')
    if phase == 'finalize':
        if not c.get('finalization_job_id'):
            raise ValueError('Finalization requires an already-started named job')
        if stage >= limits['finalization_minutes']:
            return emit('STOP_ACTIVE_WORK', 'Named-job finalization active-time allowance reached; save its resume state')
        return emit('FINISH_NAMED_JOB_ONLY', 'Reserve cannot start another source, repair or batch')
    if (active >= limits['active_minutes'] - limits['finalization_minutes']
            or (spent is not None and spent >= limits['accounted_tokens'] - limits['finalization_tokens'])):
        return emit('STOP_ACTIVE_WORK', 'Only the reserved named-job finalization allowance remains')
    if phase == 'waiting':
        return emit('WAIT_WITHOUT_MODEL', 'Record the real observer and resume command; no active polling loop')
    if purpose == 'publication' and (no_public >= limits['no_public_batches']
                                     or stagnant >= limits['stagnation_minutes']):
        return emit('STOP_ACTIVE_WORK', 'Private proofs, repairs and maintenance do not reset map stagnation')
    if purpose == 'preparation' and preparation_completed:
        return emit('STOP_ACTIVE_WORK', 'The one scoped preparation deliverable is complete; hand it off')
    if phase == 'preflight' and stage >= limits['preflight_minutes']:
        return emit('STOP_ACTIVE_WORK', 'Cheap feasibility window exhausted')
    if phase in {'qualification', 'repair'} and stage >= limits['stage_minutes']:
        return emit('STOP_ACTIVE_WORK', 'Bounded active-stage window exhausted')
    if phase == 'qualification':
        if len(pending) >= 2:
            return emit('HOLD_DISCOVERY', 'Two qualified handoffs await downstream work, including held jobs')
        if candidate is not None and candidate >= limits['candidate_tokens']:
            return emit('STOP_ACTIVE_WORK', 'Candidate allowance reached')
        if purpose == 'publication' and unready:
            return emit('PREFLIGHT_ONLY', 'Resolve downstream feasibility before more source pixels')
    if phase == 'repair':
        repair = c.get('repair', {})
        if not repair.get('failure_receipt') or repair.get('batch_id') != c['batch_id']:
            return emit('STOP_ACTIVE_WORK', 'Repair is not linked to the named reproduced batch blocker')
        if purpose == 'publication' and (repair.get('only_remaining_known_blocker') is not True
                                         or len(unready) > 1):
            return emit('STOP_ACTIVE_WORK', 'Multiple prerequisites remain; this is preparation, not an executable release')
        if repair_spent is not None and repair_spent >= limits['repair_tokens']:
            return emit('STOP_ACTIVE_WORK', 'Repair allowance reached')
        return emit('REPAIR_ONLY', 'Repair this reproduced blocker within the unchanged run allowance')
    if phase == 'preflight' and unready:
        return emit('PREFLIGHT_ONLY', 'One cheap readiness check; no qualification or release clearance')
    return emit('RUN_BOUNDED_BATCH', 'Operating allowance permits the named stage; scientific gates still apply')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', type=Path)
    args = parser.parse_args()
    try:
        result = decide(json.loads(args.checkpoint.read_text()))
    except (ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'Invalid progress control: {error}\n')
    print(json.dumps(result, indent=2))
    return 2 if result['action'] in {'STOP_ACTIVE_WORK', 'HOLD_DISCOVERY', 'PREFLIGHT_ONLY'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
