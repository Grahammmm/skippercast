"""Prepare a write-once review context from independently posted handoff Refs."""
from pathlib import Path
from review_common import (PINS, IDENTITY, GraphValidator, absolute, attempt_path,
                           document, finish, header, output, parser, pin, problem,
                           resolver_for, trusted_context, validate_schema, loads)


def prepare(resolver, inputs, review_round, attempt, out):
    context = dict(inputs, schema='coast-review-context-v1', review_round=review_round, attempt=attempt)
    validate_schema(context)
    attempt_path(context, out, 'context.json')
    # Validate identity independently before using any run/packet-derived identity.
    identity = document(resolver, context['identity_provenance'])
    for key in (*IDENTITY, 'run_author_model', 'run_card_id'):
        if identity.get(key) != context[key]:
            raise ValueError('independent identity differs: ' + key)
    posted = document(resolver, context['posted_hashes'])
    if any(context[k] is not None and posted.get(k) != context[k] for k in PINS):
        raise ValueError('posted handoff pins absent or different; corrective handoff required')
    if review_round == 1 and attempt == 1:
        if context['supersedes'] is not None or context['correction_verdict'] is not None:
            raise ValueError('initial round cannot supersede a review')
    else:
        if context['supersedes'] is None:
            raise ValueError('new round/attempt must explicitly supersede its context')
        previous = trusted_context(resolver, context['supersedes'])
        if any(previous[k] != context[k] for k in IDENTITY):
            raise ValueError('changed plan needs new admission, not review correction')
        if attempt > 1:
            if previous['review_round'] != review_round or previous['attempt'] + 1 != attempt:
                raise ValueError('attempt must increment within the same round')
        else:
            correction = context['correction_verdict']
            if correction is None:
                raise ValueError('new round requires previous must_fix verdict')
            verdict = GraphValidator(resolver).reference(correction, contract='coast-review-verdict-v1')
            if (verdict['verdict'] != 'must_fix' or verdict['context'] != context['supersedes'] or
                    previous['review_round'] + 1 != review_round):
                raise ValueError('correction does not bind immediately previous must_fix round')
    problems = list(context['observations'])
    graph = GraphValidator(resolver)
    for key in PINS:
        if context[key] is None:
            problems.append(problem('POSTED_SHA_ABSENT', key, 'independent posted Ref', None))
            continue
        try:
            value = graph.reference(context[key], contract={'admission': 'coast-admission-v1',
                'run': 'coast-run-summary-v1', 'enqueue': 'coast-enqueue-receipt-v1'}.get(key))
            if key in ('admission', 'run', 'enqueue'):
                if any(value[k] != context[k] for k in IDENTITY):
                    raise ValueError('producer identity mismatch')
            if key == 'run' and (value['author_model'] != context['run_author_model'] or value['card_id'] != context['run_card_id']):
                raise ValueError('run author/card provenance mismatch')
        except (ValueError, OSError, KeyError, TypeError) as error:
            problems.append(problem('INPUT_INVALID', key, context[key]['sha256'], str(error)))
    context.update(mode='diagnostic' if problems else 'normal', observations=problems)
    validate_schema(context)
    # Stage context once, then use its independent identity-only role to check
    # provenance/roots. The normal graph is checked before declaring ready.
    from review_common import provenance
    provenance(resolver, context['run_author_provenance'], context['run_author_model'])
    for key in ('routing', 'thresholds', 'prompts', 'identity_provenance', 'posted_hashes'):
        graph.walk(context[key], root_id='queue:' + context['campaign_segment_id'])
    if set(context['root_ids']) != set(resolver.bindings):
        raise ValueError('unexpected context root IDs')
    ref = output(resolver, out, context)
    trusted_context(resolver, ref)
    if not problems:
        GraphValidator(resolver).reference(ref, contract='coast-review-context-v1')
    return ref, bool(problems)


def main():
    cli = parser(__doc__)
    cli.add_argument('--inputs', required=True, type=absolute)
    cli.add_argument('--round', required=True, type=int)
    cli.add_argument('--attempt', required=True, type=int)
    cli.add_argument('--out', required=True, type=absolute)
    args = cli.parse_args()
    resolver = resolver_for(args)
    ref, diagnostic = prepare(resolver, loads(args.inputs.read_bytes()), args.round, args.attempt, args.out)
    import json
    print(json.dumps(dict(context=ref, diagnostic=diagnostic), sort_keys=True))
    return 3 if diagnostic else 0


if __name__ == '__main__':
    raise SystemExit(finish(main))
