"""Read-only, explicitly pinned pilot metrics. Structural validity is not acceptance.

No directory selects a canonical run or verdict: the operator's cohort freezes
all admissions, continuation snapshots, review attempts and ledger snapshots.
See references/metrics.md for the cohort and output contracts.
"""
import argparse
from datetime import datetime, timezone
import math
from pathlib import Path
import statistics
import sys

SIGN_OFF = Path(__file__).resolve().parents[2] / 'coast-sign-off/scripts'
sys.path.insert(0, str(SIGN_OFF))
from review_common import (absolute, document, observed_read, pin, finish, trusted_context,
                           reviewer, IDENTITY)
from coast_refs import Resolver, canonical, directory_fd, loads, write_once
from coast_ledger import verify_bytes
from validate_coast_receipt import GraphValidator

REQUIRED = ('valid_fraction', 'depth_median_m', 'depth_p99_m', 'nodata_fraction',
            'edge_valid_fraction', 'slope_p99_deg')
EXCLUSIONS = ('held', 'unavailable_required', 'unfinished', 'invalid_evidence',
              'unexamined', 'reference_undetermined')
STAGE_EXCLUSIONS = ('acquire_held', 'acquire_failed', 'acquire_pending', 'acquire_missing',
                    'acquire_done_without_qualify', 'qualify_held', 'qualify_failed',
                    'qualify_pending', 'map_held', 'integrity_unavailable')
LIMITATION = ('Reviewer-examined mapped complete-required-evidence cohort only; '
              'flag-enriched plus deterministic sample, not whole-coast recall. '
              'Zero sampled windows are not visual evidence. Operator readiness approval remains separate.')


def utc(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None or result.utcoffset().total_seconds() != 0:
        raise ValueError('expected timezone-explicit UTC timestamp')
    return result


def metric(value, population, evidence, reason=None, status=None):
    measured = value is not None
    return dict(status=status or ('measured' if measured else 'unavailable'), value=value,
                display=str(value) if measured else 'not measured',
                reason=reason if reason else None if measured else 'missing_evidence_or_zero_denominator',
                population=population, evidence=unique(evidence))


def unique(refs):
    return list({canonical(r): r for r in refs}.values())


def rate(numerator, denominator, population, evidence):
    return metric(numerator / denominator if denominator else None,
                  dict(population, numerator=numerator, denominator=denominator), evidence)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def identity(value, admission):
    if any(value[k] != admission[k] for k in IDENTITY):
        raise ValueError('receipt/admission identity mismatch')


class Reader:
    def __init__(self, resolver):
        self.resolver = resolver
        self.problems = []
        self.evidence = []

    def load(self, ref, contract, *, optional=False):
        if ref is None:
            return None
        try:
            result = GraphValidator(self.resolver).reference(ref, contract=contract)
            self.evidence.append(ref)
            return result
        except (ValueError, OSError, KeyError, TypeError) as error:
            if not optional:
                raise
            problem = dict(expected=ref, detail=str(error))
            if problem not in self.problems:
                self.problems.append(problem)
            return None


def stages_for(reader, window, admission):
    """Done is backed by an immutable result, not a deepest-stage inference."""
    result = {}
    for stage in window['stages']:
        name = stage['stage']
        if name in result:
            raise ValueError('ambiguous repeated stage in selected snapshot')
        result[name] = stage
        if stage['result'] is not None:
            native = document(reader.resolver, stage['result'])
            expected = dict(stage=name, job_id=stage['job_id'], state=stage['state'],
                            segment_id=admission['coordinator_segment_id'],
                            input_manifest_sha=stage['input_manifest']['sha256'], holds=stage['holds'])
            if native.get('schema') != 'coastal-stage-result-v1' or any(native.get(k) != v for k, v in expected.items()):
                raise ValueError('stage result does not bind stated execution/holds')
        elif stage['state'] == 'done':
            raise ValueError('done stage has no verified result')
    return result


def classify(stages, name):
    s = stages.get(name)
    if s is None:
        return 'missing'
    if s['state'] == 'held' or s['holds']:
        return 'held'
    if s['state'].startswith('failed') or s['state'] in ('stale', 'cancelled'):
        return 'failed'
    return 'done' if s['state'] == 'done' else 'pending'


def confusion_window(window, decision, examined):
    if window is None:
        return 'invalid_evidence'
    if window['stage_state'] == 'held':
        return 'held'
    if window['stage_state'] != 'map_done':
        return 'unfinished'
    measurements = window['measurements']
    if (any(measurements.get(n, {}).get('status') != 'measured' for n in REQUIRED)
            or any(m['status'] == 'unavailable' for m in measurements.values())
            or window['status'] == 'unavailable'):
        return 'unavailable_required'
    # Structural N/A is not a failed measurement, nor a successful numeric test.
    if window['window_key'] not in examined:
        return 'unexamined'
    if decision is None or type(decision['defect']) is not bool:
        return 'reference_undetermined'
    if window['status'] not in ('pass', 'flag'):
        return 'invalid_evidence'
    flag, defect = window['status'] == 'flag', decision['defect']
    return 'tp' if flag and defect else 'fp' if flag else 'fn' if defect else 'tn'


def select_runs(reader, item, admission):
    runs = []
    previous = None
    for ref in item['runs']:
        run = reader.load(ref, 'coast-run-summary-v1', optional=True)
        if run is None:
            return None, None, []
        identity(run, admission)
        if run['admission'] != item['admission'] or run['continuation_of'] != previous or run['sequence'] != len(runs) + 1:
            raise ValueError('run continuation/admission binding mismatch')
        if {w['window_key'] for w in run['windows']} != {w['window_key'] for w in admission['windows']}:
            raise ValueError('run does not cover all admission windows')
        previous = ref
        runs.append(run)
    return (runs[-1], previous, runs) if runs else (None, None, [])


def select_verdict(reader, item, admission):
    values = []
    for ref in item['verdicts']:
        v = reader.load(ref, 'coast-review-verdict-v1', optional=True)
        if v is None:
            return None, None, values
        identity(v, admission)
        context = trusted_context(reader.resolver, v['context'])
        reviewer(reader.resolver, context, v['reviewer_model'], v['reviewer_provenance'])
        if context['admission'] != item['admission']:
            raise ValueError('verdict context/admission mismatch')
        if v['review_round'] > 1 and context['correction_verdict'] not in [r for _, r in values]:
            raise ValueError('cohort omitted preceding corrective verdict')
        values.append((v, ref))
    ranks = [(v['review_round'], v['attempt']) for v, _ in values]
    if ranks != sorted(set(ranks)):
        raise ValueError('review attempts must be unique and explicitly round/attempt ordered')
    if not values:
        return None, None, []
    return *values[-1], values


def interim_rollup(directory, since):
    """Cycle-1 prose-card adapter. Never follow its absolute evidence paths."""
    if directory is None:
        return []
    with directory_fd(directory):
        pass
    records = []
    # Only known entry names: prior copies are not extra current observations.
    for pattern in ('tier1-*.json', 'packet-*.json'):
        for path in sorted(directory.glob(pattern)):
            if not path.stem.split('-')[-1].endswith(('D1', 'M2', 'S1')):
                continue
            raw = local_read(path)
            value = loads(raw)
            stamp = value.get('generated_at') or value.get('review_window', {}).get('end_pdt')
            if stamp and datetime.fromisoformat(stamp).astimezone(timezone.utc) < since:
                continue
            ref = local_evidence(path, raw)
            # These are observations ABOUT the interim screen, not rehashed native evidence.
            records.append(dict(label='interim', evidence=ref, run=value.get('run', value.get('run_id')),
                                producer_fields={k: value[k] for k in ('hash_mismatches', 'wall_seconds',
                                    'held', 'window_table', 'visual_review', 'flags_confirmed', 'flags_total',
                                    'review_window', 'hashes') if k in value},
                                qualify_clean_all_admitted=metric(None, {'scope': 'interim'}, [ref],
                                    'interim_has_no_verified_admitted_W_A_Q'),
                                tier1_confusion=metric(None, {'scope': 'interim'}, [ref],
                                    'no_canonical_examined_reference_population'),
                                tier2_packet_accuracy=metric(None, {'scope': 'interim'}, [ref],
                                    'tier2_self_confirmation_is_not_tier3_accuracy')))
    return records


def local_read(path):
    """Use the same no-follow bounded reader for explicitly admitted local inputs."""
    class Local:
        bindings = {'local': path.parent}
    return observed_read(Local(), path)


def local_evidence(path, raw):
    from coast_refs import sha256
    # Local input namespaces are observations, never passed to the workflow resolver.
    return dict(root_id='input:' + path.name, path=path.name, sha256=sha256(raw), bytes=len(raw))


def rollup(resolver, root, cohort, since, *, cohort_ref, interim=None, board=None):
    if set(cohort) != {'schema', 'allowed_root_ids', 'plans', 'ledgers', 'measurements'} or cohort['schema'] != 'coast-metrics-cohort-v1':
        raise ValueError('invalid explicit cohort envelope')
    if set(cohort['allowed_root_ids']) != set(resolver.bindings):
        raise ValueError('cohort/operator root inventory differs')
    for key, path in resolver.bindings.items():
        if key.startswith('queue:') and path != root / key.removeprefix('queue:'):
            raise ValueError('queue binding differs from COAST_ROOT campaign layout')
    reader = Reader(resolver)
    plans = []
    by_admission = {}
    for item in cohort['plans']:
        if set(item) != {'admission', 'runs', 'verdicts'}:
            raise ValueError('cohort plan needs explicit admission/runs/verdicts')
        a = reader.load(item['admission'], 'coast-admission-v1')
        key = canonical(item['admission'])
        if key in by_admission:
            raise ValueError('duplicate admission in cohort')
        plan = dict(item=item, admission=a, ref=item['admission'], children=[])
        by_admission[key] = plan
        plans.append(plan)
    for plan in plans:
        a = plan['admission']
        parent_ref = a['replacement_plan_of']
        if parent_ref is not None:
            parent = by_admission.get(canonical(parent_ref))
            if parent is None or parent is plan:
                raise ValueError('replacement needs its original admission in cohort')
            parent['children'].append(plan)
            # A changed inventory needs an upstream reconciled mapping, never guessed here.
            if (a['campaign_segment_id'] != parent['admission']['campaign_segment_id'] or
                    {w['window_key'] for w in a['windows']} != {w['window_key'] for w in parent['admission']['windows']}):
                raise ValueError('replacement changes inventory; explicit upstream reconciliation required')
        if len(plan['children']) > 1:
            raise ValueError('ambiguous replacement branch')
    finals = []
    visited = set()
    for plan in plans:
        if plan['admission']['replacement_plan_of'] is not None:
            continue
        chain = []
        current = plan
        while True:
            marker = canonical(current['ref'])
            if marker in visited:
                raise ValueError('cyclic/duplicate replacement')
            visited.add(marker)
            chain.append(current)
            if not current['children']:
                break
            if len(current['children']) != 1:
                raise ValueError('ambiguous replacement branch')
            current = current['children'][0]
        finals.append((plan, current, chain))
    if len(visited) != len(plans):
        raise ValueError('replacement cycle without original inventory')

    # Ledger snapshots, never append or read a mutable Store/board DB.
    ledger_rows = []
    ledger_refs = []
    for ref in cohort['ledgers']:
        raw = resolver.read(ref)
        rows = verify_bytes(raw)
        graph = GraphValidator(resolver)
        for row in rows:
            graph.document(row, root_id=ref['root_id'])
        ledger_rows.extend(rows)
        ledger_refs.append(ref)
    windows = {}
    exclusions = {k: [] for k in STAGE_EXCLUSIONS}
    confusion = {k: [] for k in (*EXCLUSIONS, 'tp', 'fp', 'fn', 'tn')}
    sampled, sampled_must, sampled_unknown = [], [], []
    W, A, Q, mapped = [], [], [], []
    rounds, minutes, accuracies, final_plans = [], [], [], []
    producer_fields, derived = [], []
    counts_evidence = [cohort_ref] + [p['ref'] for p in plans]
    all_runs, telemetry = [], []
    histories = []
    hold_dispositions = []
    for original, final, chain in finals:
        a, item = final['admission'], final['item']
        inventory_id = original['admission']['campaign_segment_id'] + '/' + original['admission']['plan_id']
        run, run_ref, runs = select_runs(reader, item, a)
        v, vref, reviews = select_verdict(reader, item, a)
        historical_reviews = []
        for member in chain:
            _, _, history = select_verdict(reader, member['item'], member['admission']) if member is not final else (v, vref, reviews)
            historical_reviews.extend(history)
        histories.extend(ref for _, ref in historical_reviews)
        if historical_reviews:
            rounds.append(len({(h['plan_sha256'], h['review_round']) for h, _ in historical_reviews}))
            minutes.append(sum(h['minutes'] for h, _ in historical_reviews))
        if v and v['tier2_packet_accuracy'] is not None:
            accuracies.append(dict(value=v['tier2_packet_accuracy'], evidence=vref, inventory=inventory_id))
        all_runs.extend((r, ref) for r, ref in zip(runs, item['runs']))
        counts_evidence.extend(item['runs'])
        packet = t1 = None
        if v and v['evidence_status'] == 'valid':
            packet = document(resolver, v['packet'])
            if run_ref is None or packet['run'] != run_ref:
                raise ValueError('final review does not bind selected final run')
            t1 = document(resolver, packet['tier1'])
            telemetry.append((t1['telemetry'], packet['tier1']))
        run_windows = {w['window_key']: w for w in run['windows']} if run else {}
        screens = {w['window_key']: w for w in t1['windows']} if t1 else {}
        decisions = {d['window_key']: d for d in v['decisions']} if v else {}
        examined = set(v['windows_examined']) if v else set()
        plan_mapped, plan_held = [], []
        for aw in a['windows']:
            wk = aw['window_key']
            key = a['campaign_segment_id'] + '/' + wk
            if key in windows:
                raise ValueError('window duplicated across nonreplacement inventories')
            W.append(key)
            rw = run_windows.get(wk)
            if run is None and item['runs']:
                exclusions['integrity_unavailable'].append(key)
            try:
                stages = stages_for(reader, rw, a) if rw else {}
            except (ValueError, KeyError) as error:
                reader.problems.append(dict(expected=run_ref, detail=str(error)))
                stages = {}
                exclusions['integrity_unavailable'].append(key)
            ac, qu, ma = (classify(stages, s) for s in ('acquire', 'qualify', 'map'))
            if ac == 'done':
                A.append(key)
                if qu == 'done':
                    Q.append(key)
                else:
                    exclusions['acquire_done_without_qualify'].append(key)
                    exclusions['qualify_' + ('pending' if qu == 'missing' else qu)].append(key)
            else:
                exclusions['acquire_' + ac].append(key)
                if qu == 'done':
                    exclusions['integrity_unavailable'].append(key)
            if ma == 'held':
                exclusions['map_held'].append(key)
            if ma == 'done' and qu == 'done' and ac == 'done':
                mapped.append(key)
                plan_mapped.append(key)
            if rw and rw['state'] == 'held':
                plan_held.append(key)
                hold_dispositions.append(dict(window=key, accepted_cause=decisions.get(wk, {}).get('accepted_cause'), evidence=vref))
            screen = screens.get(wk)
            group = confusion_window(screen, decisions.get(wk), examined)
            if (key in exclusions['integrity_unavailable'] or (v and v['evidence_status'] != 'valid') or
                    (screen and screen['stage_state'] == 'map_done' and key not in mapped)):
                group = 'invalid_evidence'
            confusion[group].append(key)
            if screen:
                producer_fields.append(dict(window=key, fields=screen['producer_fields'], evidence=packet['tier1']))
                derived.append(dict(window=key, measurements=screen['measurements'], evidence=packet['tier1']))
            if packet and wk in packet['sample']['selected']:
                sampled.append(key)
                if group in EXCLUSIONS:
                    sampled_unknown.append(key)
                if decisions.get(wk, {}).get('defect') is True or any(f['window_key'] in (None, wk) for f in v['must_fix']):
                    sampled_must.append(key)
            windows[key] = dict(inventory=inventory_id, admission=final['ref'], run=run_ref, verdict=vref,
                                acquire=ac, qualify=qu, map=ma, confusion_group=group)
        ledger_ok = bool(vref) and any(r.get('ledger_role') == 'segment' and r.get('verdict_file') == vref for r in ledger_rows)
        segment_rows = [r for r in ledger_rows if r.get('ledger_role') == 'segment' and r.get('verdict_file') == vref]
        from coast_refs import sha256
        ledger_ok = ledger_ok and any(r.get('ledger_role') == 'campaign' and r.get('verdict_file') == vref and
            r['segment_row_sha256'] in {sha256(canonical(s)) for s in segment_rows} for r in ledger_rows)
        final_plans.append(dict(inventory=inventory_id, accepted=bool(v and v['verdict'] == 'accept' and ledger_ok),
                                mapped=bool(plan_mapped) and len(plan_mapped) == len(a['windows']),
                                accepted_held=bool(plan_held), evidence=vref,
                                finished_utc=v['created_utc'] if v else None))
    counts_evidence = unique(counts_evidence)
    cohort_pop = dict(scope='all distinct admitted inventory windows; replacement attempts deduplicated', windows=W)
    metrics = {
        'qualify_clean_all_admitted': rate(len(Q), len(W), cohort_pop, counts_evidence),
        'qualify_clean_given_acquire_done': rate(len(Q), len(A), dict(scope='conditional on verified acquire.done', windows=A), counts_evidence),
        'map_done': metric(len(mapped), cohort_pop, counts_evidence),
    }
    examined_keys = sum((confusion[k] for k in ('tp', 'fp', 'fn', 'tn')), [])
    c = {k: len(confusion[k]) for k in ('tp', 'fp', 'fn', 'tn')}
    review_pop = dict(scope='windows_examined mapped complete-required-evidence definite decisions', windows=examined_keys, sampling_bias=LIMITATION)
    metrics.update(
        screener_recall=rate(c['tp'], c['tp'] + c['fn'], review_pop, histories),
        screener_precision=rate(c['tp'], c['tp'] + c['fp'], review_pop, histories),
        screener_misses=metric(c['fn'] if examined_keys else None, review_pop, histories),
        sampled_must_fix=metric(len(sampled_must) if sampled and not sampled_unknown else None,
                               dict(scope='deterministic sample', windows=sampled, unavailable=sampled_unknown), histories),
        review_rounds_median=metric(statistics.median(rounds) if len(rounds) == len(finals) and rounds else None,
                                   dict(scope='review rounds per original inventory', values=rounds), histories),
        reviewer_minutes_per_plan=metric(statistics.median(minutes) if len(minutes) == len(finals) and minutes else None,
                                   dict(scope='median total actual review minutes per original inventory', values=minutes), histories),
        tier2_packet_accuracy=metric(statistics.mean(x['value'] for x in accuracies) if accuracies else None,
                                   dict(scope='unweighted mean of measured final verdict accuracies; missing excluded', measured=accuracies,
                                        unavailable_plans=len(finals)-len(accuracies)), [x['evidence'] for x in accuracies]),
    )
    finish_times = [utc(p['finished_utc']) for p in final_plans if p['finished_utc']]
    elapsed = (max(finish_times) - since).total_seconds() / 86400 if finish_times else 0
    accepted = [p for p in final_plans if p['accepted'] and utc(p['finished_utc']) >= since]
    for name, subset in (('accepted_plans_per_day', accepted),
                         ('mapped_plans_per_day', [p for p in accepted if p['mapped']]),
                         ('accepted_held_plans_per_day', [p for p in accepted if p['accepted_held']])):
        metrics[name] = rate(len(subset), elapsed if elapsed > 0 else 0,
                            dict(scope='distinct final accepted original inventories / observation days',
                                 inventories=[p['inventory'] for p in subset]), histories + ledger_refs)
    metrics['pipeline_wall_s'] = metric(sum(r['wall_s'] for r, _ in all_runs) if all_runs else None,
        dict(scope='all explicit continuation executions; CPU/network mapping separate from model time'), [ref for _, ref in all_runs])
    metrics['pipeline_bytes'] = metric(sum(r['usage']['bytes'] for r, _ in all_runs) if all_runs else None,
        dict(scope='producer run usage bytes, not source-deduplicated cap accounting'), [ref for _, ref in all_runs])
    metrics['local_tokens'] = metric(sum(t['tokens'] for t, _ in telemetry) if telemetry and all(t['tokens'] is not None for t, _ in telemetry) else None,
        dict(scope='final tier1 measured telemetry only'), [ref for _, ref in telemetry])
    metrics['local_latency_s'] = metric(sum(t['wall_s'] for t, _ in telemetry) if telemetry else None,
        dict(scope='final tier1 measured telemetry only'), [ref for _, ref in telemetry])
    # No proxy from hillshade, dry-run, per-job storage or model tokens.
    for name in ('contour_visual_clean', 'n16_within_budget', 'cache_peak_bytes', 'token_cost', 'projected_coast_days'):
        metrics[name] = supplementary(reader, cohort['measurements'].get(name), name)
    unknown = set(cohort['measurements']) - {'contour_visual_clean', 'n16_within_budget', 'cache_peak_bytes', 'token_cost', 'projected_coast_days'}
    if unknown:
        raise ValueError('unknown supplementary measurements')
    metrics['operator_rescues'] = board_metric(board, since, cohort_ref)
    integrity_refs = histories + ledger_refs + counts_evidence

    # Diagnostic findings are not erased by an accepted cause.
    diagnostic = []
    for p in plans:
        for ref in p['item']['verdicts']:
            v = reader.load(ref, 'coast-review-verdict-v1', optional=True)
            if v and v['evidence_status'] == 'invalid':
                diagnostic.extend(v['must_fix'])
    # Scan final T1/T2 flags and open reports, not hash-like strings in provenance.
    hash_findings = [f for f in diagnostic if f['code'] in ('HASH_MISMATCH', 'MISSING_FILE', 'BYTES_MISMATCH')]
    for ref in histories:
        verdict = document(resolver, ref)
        if verdict['packet'] is not None:
            packet = document(resolver, verdict['packet'])
            hash_findings.extend(f for f in packet['flags'] if f['code'] in ('HASH_MISMATCH', 'MISSING_FILE', 'BYTES_MISMATCH'))
    metrics['broken_receipts'] = metric(len(reader.problems) + len(diagnostic),
        dict(scope='explicit cohort graphs plus corrective integrity findings', diagnostic_findings=diagnostic), integrity_refs)
    metrics['hash_mismatches'] = metric(len(hash_findings) if histories and not reader.problems else None,
        dict(scope='verified T1/T2 flags and corrective open-report findings', findings=hash_findings), integrity_refs)
    complete = (bool(W) and not reader.problems and not diagnostic and
                not exclusions['acquire_missing'] and not exclusions['integrity_unavailable'] and
                not confusion['invalid_evidence'] and not confusion['unavailable_required'])
    return dict(schema='coast-pilot-metrics-v1', since=since.isoformat().replace('+00:00', 'Z'),
                review_required=True, limitations=LIMITATION, evidence_complete=complete,
                inventory=dict(W=len(W), A=len(A), Q=len(Q), windows=windows, evidence=counts_evidence,
                               replacement_exclusions=[p['ref'] for p in plans if p['children']],
                               exclusions={k: dict(count=len(set(v)), windows=sorted(set(v))) for k,v in exclusions.items()}),
                confusion=dict(counts=c, groups=confusion, population=review_pop, evidence=histories),
                holds=hold_dispositions, final_plans=final_plans, metrics=metrics,
                diagnostic_findings=diagnostic, broken_evidence=reader.problems,
                producer_fields=producer_fields, derived_measurements=derived,
                interim=interim_rollup(interim, since))


def supplementary(reader, ref, name):
    if ref is None:
        return metric(None, {'scope': name}, [], 'separate_actual_evidence_not_supplied')
    value = document(reader.resolver, ref)
    if set(value) != {'schema', 'metric', 'measurement', 'population', 'evidence', 'reviewer_verdict'} or value['schema'] != 'coast-pilot-measurement-v1' or value['metric'] != name:
        raise ValueError('invalid supplementary measurement envelope')
    for evidence in value['evidence']:
        reader.resolver.read(evidence)
    verdict = reader.load(value['reviewer_verdict'], 'coast-review-verdict-v1')
    if verdict['evidence_status'] != 'valid' or verdict['verdict'] != 'accept' or not value['evidence']:
        return metric(None, value['population'], [ref], 'separate_evidence_not_accepted')
    context = trusted_context(reader.resolver, verdict['context'])
    reviewer(reader.resolver, context, verdict['reviewer_model'], verdict['reviewer_provenance'])
    reviewed = {canonical(r) for d in verdict['decisions'] for r in d['evidence']}
    if not all(canonical(r) in reviewed for r in value['evidence']):
        return metric(None, value['population'], [ref], 'supplementary_artifacts_not_in_reviewer_decisions')
    # The measurement is a separately reviewed actual observation, not a model estimate.
    m = value['measurement']
    if set(m) != {'status', 'value', 'reason', 'method_version'} or m['status'] not in ('measured', 'unavailable', 'not_applicable'):
        raise ValueError('invalid measurement status')
    if not isinstance(m['method_version'], str) or not m['method_version']:
        raise ValueError('measurement requires actual method/version')
    if m['status'] != 'measured':
        return metric(None, value['population'], [ref], m['reason'], status=m['status'])
    if name in ('contour_visual_clean', 'n16_within_budget'):
        if type(m['value']) is not bool:
            raise ValueError('criterion observation must be boolean')
    elif not finite(m['value']):
        raise ValueError('measurement must be a nonnegative finite number')
    if name == 'n16_within_budget':
        runs = []
        for r in value['evidence']:
            if r['path'].endswith('.json'):
                native = document(reader.resolver, r)
                if native.get('schema') == 'coast-run-summary-v1':
                    run = reader.load(r, 'coast-run-summary-v1')
                    admission = reader.load(run['admission'], 'coast-admission-v1')
                    if len(admission['windows']) == 16 and len(run['windows']) == 16:
                        verified = all(all(classify(stages_for(reader, w, admission), s) == 'done'
                                           for s in ('acquire', 'qualify', 'map')) for w in run['windows'])
                        actual = verified and all(document(reader.resolver, s['result']).get('provenance', {}).get('synthetic') is False
                                     for w in run['windows'] for s in w['stages'] if s['stage'] in ('acquire', 'qualify', 'map'))
                        if verified and actual:
                            runs.append((run, admission))
        if len(runs) != 1:
            return metric(None, value['population'], [ref], 'no_single_actual_complete_N16_execution')
        run, admission = runs[0]
        within = run['wall_s'] <= admission['budgets']['wall_s'] and run['usage']['bytes'] <= admission['budgets']['bytes']
        if m['value'] != within:
            raise ValueError('N16 measurement differs from actual time/byte budget evidence')
    return metric(m['value'], value['population'], [ref] + value['evidence'] + [value['reviewer_verdict']])


def board_metric(board, since, cohort_ref):
    if board is None:
        return metric(None, {'scope': 'board events'}, [], 'no_board_event_export')
    raw = local_read(board)
    value = loads(raw)
    if set(value) != {'schema', 'since', 'until', 'cohort', 'events'} or value['schema'] != 'coast-board-events-v1' or value['cohort'] != cohort_ref:
        raise ValueError('invalid cohort-bound board event export')
    if utc(value['since']) != since or utc(value['until']) <= since:
        raise ValueError('board event export period differs')
    events = value['events']
    ids = set()
    for event in events:
        if set(event) != {'id', 'created_utc', 'operator_rescue'} or type(event['operator_rescue']) is not bool or event['id'] in ids:
            raise ValueError('invalid/duplicate exported event')
        if not since <= utc(event['created_utc']) <= utc(value['until']):
            raise ValueError('event outside exported period')
        ids.add(event['id'])
    return metric(sum(e['operator_rescue'] for e in events),
                  dict(scope='complete cohort-scoped exported board period', since=value['since'], until=value['until']),
                  [local_evidence(board, raw)])


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ('roots', 'root', 'cohort', 'out'):
        cli.add_argument('--' + name, required=True, type=absolute)
    cli.add_argument('--since', required=True)
    cli.add_argument('--interim', type=absolute)
    cli.add_argument('--board-events', type=absolute)
    args = cli.parse_args()
    raw = local_read(args.cohort)
    cohort = loads(raw)
    resolver = Resolver(loads(local_read(args.roots)), allowed_root_ids=cohort['allowed_root_ids'])
    result = rollup(resolver, args.root, cohort, utc(args.since),
                    cohort_ref=local_evidence(args.cohort, raw), interim=args.interim, board=args.board_events)
    with directory_fd(args.out.parent):
        pass
    write_once(args.out, result)
    print('Pilot metrics written; review required; no readiness gate granted.')
    return 0


if __name__ == '__main__':
    raise SystemExit(finish(main))
