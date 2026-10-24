"""Write immutable review evidence and both chained ledgers; print board actions only."""
import json
import math
from review_common import (GraphValidator, HEADER, IDENTITY, absolute, attempt_path,
                           document, finish, finding, output, parser, pin, resolver_for,
                           review_base, reviewer, trusted_context, validate, loads, canonical)
from open_packet import check_packet, REQUIRED
from coast_ledger import append_index


def board_action(verdict, review_round):
    if verdict == 'accept':
        return dict(action='complete_review_and_create_next_admission', review_completed=True,
                    next_inventory_authorized=True, publication_authorized=False)
    if verdict == 'must_fix':
        return dict(action='complete_review_and_create_correction_chain', review_completed=True,
                    next_round=review_round + 1, next_inventory_authorized=False,
                    correction_reviewer='fable-2nd-look' if review_round >= 3 else 'independent_model')
    return dict(action='block_current_review_external_dependency', review_completed=False,
                next_inventory_authorized=False)


def metrics(resolver, packet, decisions):
    t1 = document(resolver, packet['tier1'])
    by_key = {w['window_key']: w for w in t1['windows']}
    selected = {d['window_key']: d for d in decisions}
    if len(selected) != len(decisions) or not set(selected) <= set(by_key):
        raise ValueError('duplicate or unadmitted reviewer window')
    counts = dict(tp=0, fp=0, fn=0, tn=0)
    excluded = dict(held=[], unavailable_required=[], unfinished=[], invalid_evidence=[],
                    unexamined=[], reference_undetermined=[])
    for key, w in by_key.items():
        # Closure acceptance is NEVER a quality reference label.
        if w['stage_state'] == 'held':
            excluded['held'].append(key)
        elif w['stage_state'] != 'map_done':
            excluded['unfinished'].append(key)
        elif (any(w['measurements'][n]['status'] != 'measured' for n in REQUIRED) or
              any(m['status'] == 'unavailable' for m in w['measurements'].values()) or w['status'] == 'unavailable'):
            excluded['unavailable_required'].append(key)
        elif key not in selected:
            excluded['unexamined'].append(key)
        elif selected[key]['defect'] is None:
            excluded['reference_undetermined'].append(key)
        elif w['status'] not in ('pass', 'flag'):
            excluded['invalid_evidence'].append(key)
        else:
            flag, defect = w['status'] == 'flag', selected[key]['defect']
            counts['tp' if flag and defect else 'fp' if flag else 'fn' if defect else 'tn'] += 1
    excluded = {k: sorted(v) for k, v in excluded.items()}
    confusion = dict(counts, excluded=sorted(k for group in excluded.values() for k in group),
                     population_definition='windows_examined: reviewer-examined map_done, verified integrity, complete required measurements, definite reference decision; sampled/flag-enriched, not whole-coast recall')
    recall_den = counts['tp'] + counts['fn']
    precision_den = counts['tp'] + counts['fp']
    summary = dict(recall=counts['tp'] / recall_den if recall_den else None,
                   precision=counts['tp'] / precision_den if precision_den else None,
                   misses=counts['fn'], exclusions=excluded,
                   population='windows_examined', sampling_bias='flag-enriched plus deterministic sample; no whole-coast detection claim')
    return confusion, summary


def validate_decisions(value):
    required = {'verdict', 'decisions', 'must_fix', 'tier2_assessments', 'external_blocker'}
    if not isinstance(value, dict) or set(value) != required or value['verdict'] not in ('accept', 'must_fix', 'hold'):
        raise ValueError('invalid bounded decisions envelope')
    if any(not isinstance(value[k], list) for k in ('decisions', 'must_fix', 'tier2_assessments')):
        raise ValueError('decisions/findings/assessments must be arrays')
    for d in value['decisions']:
        if (not isinstance(d, dict) or set(d) != {'window_key', 'defect', 'accepted_cause', 'detail', 'evidence'} or
                type(d['defect']) not in (bool, type(None))):
            raise ValueError('defect must be boolean or null; complete typed decision required')
    if value['verdict'] == 'hold':
        blocker = value['external_blocker']
        if (not isinstance(blocker, dict) or set(blocker) != {'kind', 'detail'} or
                blocker['kind'] not in ('endpoint', 'medium', 'operator_decision') or not blocker['detail']):
            raise ValueError('hold requires genuine external endpoint/medium/operator decision')
    elif value['external_blocker'] is not None:
        raise ValueError('non-hold cannot carry external blocker')


def write_verdict(resolver, context_ref, report_ref, decisions, minutes, out, ledger, campaign_ledger):
    validate_decisions(decisions)
    if not math.isfinite(minutes) or minutes < 0:
        raise ValueError('minutes must be finite and nonnegative')
    context = trusted_context(resolver, context_ref)
    report = GraphValidator(resolver).reference(report_ref, contract='coast-open-report-v1')
    if report['context'] != context_ref:
        raise ValueError('open-report does not pin this exact trusted context')
    runtime = reviewer(resolver, context, report['reviewer_model'], report['reviewer_provenance'])
    attempt_path(context, out, 'tier3/verdict.json')
    queue = resolver.bindings['queue:' + context['campaign_segment_id']]
    if ledger != queue / 'ledger.jsonl' or campaign_ledger != queue.parent / 'campaign-ledger.jsonl':
        raise ValueError('ledger paths must be fixed campaign workflow paths')
    common = dict(review_base('review-verdict', context, context_ref, runtime), open_report=report_ref,
                  reviewer_model=report['reviewer_model'], reviewer_provenance=report['reviewer_provenance'],
                  minutes=minutes, expected_packet=report['expected_packet'], observed_packet=report['observed_packet'])
    summary = dict(recall=None, precision=None, misses=None, population='not measured: integrity_failure')
    if not report['integrity_ok']:
        # Authoritative error mode: no semantic input can override the report.
        must = [finding(p['code'], p['path'] + ': ' + str(p['observed'])) for p in report['problems']]
        verdict = dict(common, evidence_status='invalid', verdict='must_fix', packet=None,
                       must_fix=must, decisions=[], windows_examined=[], next_tile_card_authorized=False,
                       population=None, tier1_confusion=None, tier2_packet_accuracy=None,
                       metrics_unavailable_reason='integrity_failure', validation_scope='identity_snapshot')
    else:
        expected = report['expected_packet']
        observed = report['observed_packet']
        if expected['expected_sha256'] is None or observed['observed_sha256'] != expected['expected_sha256']:
            raise ValueError('normal open report does not authenticate packet bytes')
        packet_ref = dict(root_id=expected['root_id'], path=expected['path'],
                          sha256=expected['expected_sha256'], bytes=observed['observed_bytes'])
        packet, _ = check_packet(resolver, context_ref, packet_ref)
        must = list(decisions['must_fix'])
        semantic = decisions['decisions']
        confusion, summary = metrics(resolver, packet, semantic)
        for d in semantic:
            if d['defect'] is True:
                must.append(finding('REVIEWER_DEFECT', d['detail'], d['window_key']))
        unresolved = [f for f in packet['flags'] if f['severity'] == 'must']
        choice = decisions['verdict']
        if choice == 'accept':
            if must or unresolved:
                raise ValueError('accept refused: must-fix findings (including HASH_MISMATCH/REQUESTS_NONZERO) remain')
            required_keys = set(packet['population']['flagged']) | set(packet['sample']['selected'])
            by_key = {d['window_key']: d for d in semantic}
            if not required_keys <= set(by_key):
                raise ValueError('accept requires every flag and sampled window examined')
            needs_cause = (set(packet['population']['held']) | set(packet['population']['unfinished']) |
                           set(packet['population']['unavailable']))
            for key in required_keys:
                d = by_key[key]
                if key in needs_cause:
                    if not d['accepted_cause']:
                        raise ValueError('accept requires explicit closure cause for held/unavailable/unfinished evidence')
                elif d['defect'] is None:
                    raise ValueError('accept requires definite reference decisions for mapped complete evidence')
        if choice == 'must_fix':
            must.extend(f for f in unresolved if f not in must)
            if not must:
                raise ValueError('must_fix requires numbered corrective findings')
        assessments = decisions['tier2_assessments']
        assessed = set()
        confirmed = 0
        for item in assessments:
            if (not isinstance(item, dict) or set(item) != {'finding_index', 'confirmed'} or
                    type(item['finding_index']) is not int or type(item['confirmed']) is not bool):
                raise ValueError('tier2 assessment needs finding_index and definite boolean confirmed')
            index = item['finding_index']
            if index in assessed or index < 0 or index >= len(packet['flags']):
                raise ValueError('duplicate or unknown packet finding assessment')
            assessed.add(index)
            confirmed += item['confirmed']
        accuracy = confirmed / len(assessed) if assessed else None
        verdict = dict(common, evidence_status='valid', verdict=choice, packet=packet_ref,
                       must_fix=must, decisions=semantic, windows_examined=sorted(d['window_key'] for d in semantic),
                       next_tile_card_authorized=choice == 'accept', population=packet['population'],
                       tier1_confusion=confusion, tier2_packet_accuracy=accuracy,
                       metrics_unavailable_reason=None if assessed else 'tier2_findings_not_measured', validation_scope='full_graph')
        summary['tier2_accuracy_population'] = dict(assessed=len(assessed), total=len(packet['flags']))
    validate(verdict, resolver, root_id=context_ref['root_id'])
    if out.exists():
        # Recovery after a cross-ledger crash only; exact bytes and decisions must
        # reproduce the immutable verdict. Never replace an existing artifact.
        existing = document(resolver, pin(resolver, out))
        if canonical(existing) != canonical(verdict):
            raise ValueError('existing verdict differs; new attempt required')
        verdict_ref = pin(resolver, out)
    else:
        verdict_ref = output(resolver, out, verdict)
    payload = dict(schema='coast-segment-ledger-v1', **{k: verdict[k] for k in (*HEADER, *IDENTITY)},
                   kind='verdict', review_round=context['review_round'], attempt=context['attempt'],
                   ledger_role='segment', segment_row_sha256=None, verdict=verdict['verdict'],
                   verdict_file=verdict_ref, context=context_ref, packet=verdict['packet'],
                   open_report=report_ref, validation_scope=verdict['validation_scope'])
    result = append_index(ledger, campaign_ledger, payload, writer='write_verdict.py',
                          resolver=resolver, root_id=context_ref['root_id'])
    return dict(verdict=verdict_ref, board_action=board_action(verdict['verdict'], context['review_round']),
                metrics=summary, ledgers=result)


def main():
    cli = parser(__doc__)
    cli.add_argument('--context', required=True, type=absolute)
    cli.add_argument('--expected-context-sha256', required=True)
    cli.add_argument('--open-report', required=True, type=absolute)
    cli.add_argument('--expected-open-report-sha256', required=True)
    cli.add_argument('--decisions', required=True, type=absolute)
    cli.add_argument('--minutes', required=True, type=float)
    cli.add_argument('--out', required=True, type=absolute)
    cli.add_argument('--ledger', required=True, type=absolute)
    cli.add_argument('--campaign-ledger', required=True, type=absolute)
    args = cli.parse_args()
    resolver = resolver_for(args)
    decisions_ref = pin(resolver, args.decisions)
    result = write_verdict(resolver, pin(resolver, args.context, args.expected_context_sha256),
                           pin(resolver, args.open_report, args.expected_open_report_sha256),
                           document(resolver, decisions_ref), args.minutes, args.out, args.ledger, args.campaign_ledger)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(finish(main))
